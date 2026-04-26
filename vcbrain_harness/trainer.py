"""
Continuous training feedback loop for the GLiNER2 context compactor.

After each successful `solve()` call, this module:

  1. Inspects the LLM-generated brief to determine which raw facts were "used"
     (referenced in `key_facts`, `red_flags`, or the `one_line_summary`).
  2. Labels each fact as `critical` / `useful` / `supplementary` based on
     whether/where it appears in the brief.
  3. Appends a JSONL training example to `training_data/examples.jsonl`.

When the example log crosses `TRAINING_BATCH_THRESHOLD` (default 50), the
trainer runs a LoRA fine-tuning cycle on the accumulated examples and saves
the result to `models/latest/`. The compactor will pick up the new model on
its next call (after `reset_model_cache()`).

Training is opt-in for offline runs (`run_training_cycle()` can be invoked
manually) and best-effort during online `solve()` calls — failures never
block brief generation.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

HARNESS_DIR = Path(__file__).parent
TRAINING_DATA_DIR = HARNESS_DIR / "training_data"
EXAMPLES_FILE = TRAINING_DATA_DIR / "examples.jsonl"
MODEL_OUTPUT_DIR = HARNESS_DIR / "models" / "latest"
TRAINING_STATE_FILE = TRAINING_DATA_DIR / "training_state.json"


# ── Labelling logic ──────────────────────────────────────────────────────────

def _brief_text(brief: dict) -> str:
    """Flatten the brief into a single lowercased searchable blob."""
    return json.dumps(brief, default=str).lower()


def _key_facts_text(brief: dict) -> str:
    """Just the key_facts + red_flags portion (used = critical signal)."""
    parts: list[str] = []
    for kf in brief.get("key_facts", []) or []:
        if isinstance(kf, dict):
            parts.append(str(kf.get("claim", "")))
        else:
            parts.append(str(kf))
    for flag in brief.get("red_flags", []) or []:
        parts.append(str(flag))
    parts.append(str(brief.get("one_line_summary", "")))
    return " ".join(parts).lower()


def _label_fact(fact: dict, key_text: str, full_text: str) -> str:
    """Heuristic weak supervision: where does the fact's value appear?"""
    value = str(fact.get("value", "")).lower().strip()
    attr = str(fact.get("attribute", "")).lower().strip()

    if not value:
        return "supplementary"

    # Truncate long values so we don't fail to match on a substring
    needle = value[:40]

    if needle and needle in key_text:
        return "critical"
    if attr and attr in key_text:
        return "critical"
    if needle and needle in full_text:
        return "useful"
    if attr and attr in full_text:
        return "useful"
    return "supplementary"


# ── Public API ───────────────────────────────────────────────────────────────

def log_training_example(
    raw_facts: list[dict],
    brief: dict,
    company_name: str,
) -> None:
    """
    Append one weak-supervision training example to examples.jsonl.

    The example uses GLiNER2's expected JSONL format:
        {"input": "<text>", "output": {"classifications": {"relevance": "<label>"}}}

    One JSONL row is written per fact (so a single solve() with N facts
    produces N rows).
    """
    if not raw_facts:
        return

    TRAINING_DATA_DIR.mkdir(parents=True, exist_ok=True)

    full_text = _brief_text(brief)
    key_text = _key_facts_text(brief)

    timestamp = datetime.now(timezone.utc).isoformat()

    rows: list[dict] = []
    for fact in raw_facts:
        src = fact.get("source")
        src_label = src["type"] if src and isinstance(src, dict) else "unknown"
        text = (
            f"{fact.get('attribute', '')}: {fact.get('value', '')} "
            f"(confidence={fact.get('confidence', 0)}, source={src_label})"
        )
        label = _label_fact(fact, key_text, full_text)

        rows.append({
            "input": text,
            "output": {
                "classifications": {"relevance": label},
            },
            "meta": {
                "company": company_name,
                "attribute": fact.get("attribute"),
                "timestamp": timestamp,
            },
        })

    with EXAMPLES_FILE.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    logger.info(
        "Logged %d training examples for %s (total file: %s)",
        len(rows), company_name, EXAMPLES_FILE,
    )


def _count_examples() -> int:
    if not EXAMPLES_FILE.exists():
        return 0
    with EXAMPLES_FILE.open("r", encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def _load_training_state() -> dict:
    if not TRAINING_STATE_FILE.exists():
        return {"last_trained_at_examples": 0, "training_runs": 0}
    try:
        return json.loads(TRAINING_STATE_FILE.read_text())
    except Exception:
        return {"last_trained_at_examples": 0, "training_runs": 0}


def _save_training_state(state: dict) -> None:
    TRAINING_DATA_DIR.mkdir(parents=True, exist_ok=True)
    TRAINING_STATE_FILE.write_text(json.dumps(state, indent=2))


def maybe_run_training() -> bool:
    """
    Trigger a training cycle if enough new examples have accumulated since
    the last run. Returns True if training ran. Best-effort: any error is
    caught and logged.
    """
    threshold = int(os.environ.get("TRAINING_BATCH_THRESHOLD", "50"))
    auto = os.environ.get("AUTO_TRAIN", "false").lower() in ("1", "true", "yes")
    if not auto:
        return False

    state = _load_training_state()
    current = _count_examples()
    delta = current - int(state.get("last_trained_at_examples", 0))

    if delta < threshold:
        return False

    try:
        run_training_cycle()
        state["last_trained_at_examples"] = current
        state["training_runs"] = int(state.get("training_runs", 0)) + 1
        state["last_run_at"] = datetime.now(timezone.utc).isoformat()
        _save_training_state(state)
        return True
    except Exception as exc:
        logger.warning("Training cycle failed (%s)", exc)
        return False


def run_training_cycle() -> dict[str, Any]:
    """
    Fine-tune GLiNER2 on the accumulated training examples using LoRA.

    Returns a dict with training stats. Caller is responsible for catching
    exceptions if running synchronously inside a request handler.
    """
    if not EXAMPLES_FILE.exists() or _count_examples() == 0:
        raise RuntimeError(f"No training examples found at {EXAMPLES_FILE}")

    try:
        from gliner2 import GLiNER2  # type: ignore
        from gliner2.training.data import (  # type: ignore
            Classification,
            InputExample,
            TrainingDataset,
        )
        from gliner2.training.trainer import (  # type: ignore
            GLiNER2Trainer,
            TrainingConfig,
        )
    except ImportError as exc:
        raise RuntimeError(
            "gliner2 package not installed. Run `pip install gliner2`."
        ) from exc

    examples: list[InputExample] = []
    with EXAMPLES_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = row.get("input", "")
            label = (
                row.get("output", {})
                .get("classifications", {})
                .get("relevance", "useful")
            )
            examples.append(
                InputExample(
                    text=text,
                    classifications=[
                        Classification(
                            task="relevance",
                            labels=["critical", "useful", "supplementary"],
                            true_label=label,
                        )
                    ],
                )
            )

    if len(examples) < 10:
        raise RuntimeError(
            f"Need at least 10 examples to train, found {len(examples)}"
        )

    dataset = TrainingDataset(examples)
    train_data, val_data, _ = dataset.split(
        train_ratio=0.9, val_ratio=0.1, test_ratio=0.0, shuffle=True, seed=42
    )

    MODEL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    base_model = os.environ.get("GLINER2_BASE_MODEL", "fastino/gliner2-base-v1")
    model = GLiNER2.from_pretrained(base_model)

    config = TrainingConfig(
        output_dir=str(MODEL_OUTPUT_DIR),
        experiment_name="vcbrain_compactor",
        num_epochs=int(os.environ.get("TRAIN_EPOCHS", "5")),
        batch_size=int(os.environ.get("TRAIN_BATCH_SIZE", "8")),
        encoder_lr=5e-6,
        task_lr=1e-4,
        warmup_ratio=0.1,
        scheduler_type="cosine",
        eval_strategy="epoch",
        save_best=True,
        early_stopping=True,
        early_stopping_patience=3,
        use_lora=True,
        lora_r=16,
        lora_alpha=32.0,
    )

    trainer = GLiNER2Trainer(model, config)
    results = trainer.train(train_data=train_data, eval_data=val_data)

    # Reload the compactor's model on next call
    try:
        from vcbrain_harness.compactor import reset_model_cache

        reset_model_cache()
    except Exception:
        pass

    logger.info(
        "Training complete — %d examples, best metric: %s",
        len(examples),
        results.get("best_metric"),
    )

    return {
        "n_examples": len(examples),
        "n_train": len(train_data.examples),
        "n_val": len(val_data.examples),
        "best_metric": results.get("best_metric"),
        "model_dir": str(MODEL_OUTPUT_DIR),
    }


if __name__ == "__main__":
    # Manual trigger: `python -m vcbrain_harness.trainer`
    logging.basicConfig(level=logging.INFO)
    stats = run_training_cycle()
    print(json.dumps(stats, indent=2))
