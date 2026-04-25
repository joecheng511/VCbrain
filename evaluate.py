"""
VCbrain evaluator — scores a harness iteration on three dimensions:

  Accuracy     40%  key_facts grounded in source data; hallucinations penalised
  Completeness 30%  must_mention items covered in the output
  Format       30%  valid JSON with all required fields and valid verdict value

Reads test_cases.json from ./vcbrain_tasks/ and imports solve() from ./harness.py
(PolyHarness sets sys.path so the iteration's harness.py is importable as 'harness').

Prints the final score as JSON so PolyHarness can parse it:
  {"score": 0.75, "details": {...}}
"""

import json
import os
import sys
import traceback
from pathlib import Path

# ── locate test cases ────────────────────────────────────────────────────────

TASK_FILE = Path(__file__).parent / "vcbrain_tasks" / "test_cases.json"
if not TASK_FILE.exists():
    # fallback: look relative to cwd
    TASK_FILE = Path("vcbrain_tasks") / "test_cases.json"

with open(TASK_FILE) as f:
    TEST_CASES = json.load(f)

# ── import harness ───────────────────────────────────────────────────────────

from harness import solve  # noqa: E402 — PolyHarness puts the iteration dir on sys.path

# ── scoring helpers ──────────────────────────────────────────────────────────

REQUIRED_FIELDS = {"company", "verdict", "key_facts", "red_flags",
                   "questions_for_founder", "one_line_summary"}
VALID_VERDICTS = {"strong_pass", "pass", "borderline", "fail"}
VERDICT_NEIGHBOURS = {
    "strong_pass": {"strong_pass", "pass"},
    "pass": {"strong_pass", "pass", "borderline"},
    "borderline": {"pass", "borderline", "fail"},
    "fail": {"borderline", "fail"},
}


def score_format(brief: dict) -> float:
    """30% weight — valid JSON structure with all required fields."""
    if not isinstance(brief, dict):
        return 0.0
    missing = REQUIRED_FIELDS - brief.keys()
    field_score = 1.0 - (len(missing) / len(REQUIRED_FIELDS))
    verdict_ok = brief.get("verdict") in VALID_VERDICTS
    key_facts_ok = isinstance(brief.get("key_facts"), list)
    return field_score * (1.0 if verdict_ok else 0.5) * (1.0 if key_facts_ok else 0.7)


def score_completeness(brief: dict, must_mention: list[str]) -> float:
    """30% weight — must_mention items present somewhere in the output."""
    if not must_mention:
        return 1.0
    output_text = json.dumps(brief).lower()
    hits = sum(1 for item in must_mention if item.lower() in output_text)
    return hits / len(must_mention)


def score_accuracy(brief: dict, expected: dict) -> float:
    """
    40% weight — two sub-checks:
      (a) Verdict alignment:     exact match=1.0, neighbour=0.6, far=0.2
      (b) Hallucination penalty: must_not_hallucinate items absent from output
    """
    # (a) verdict alignment
    actual_verdict = brief.get("verdict", "")
    expected_verdict = expected.get("verdict", "")
    if actual_verdict == expected_verdict:
        verdict_score = 1.0
    elif actual_verdict in VERDICT_NEIGHBOURS.get(expected_verdict, set()):
        verdict_score = 0.6
    else:
        verdict_score = 0.2

    # (b) hallucination check
    must_not = expected.get("must_not_hallucinate", [])
    if not must_not:
        hallucination_score = 1.0
    else:
        output_text = json.dumps(brief).lower()
        hallu_hits = sum(1 for item in must_not if item.lower() in output_text)
        # each hallucination costs 0.3, floored at 0
        hallucination_score = max(0.0, 1.0 - hallu_hits * 0.3)

    return 0.5 * verdict_score + 0.5 * hallucination_score


# ── main eval loop ───────────────────────────────────────────────────────────

def run_evaluation() -> dict:
    results = []
    total_format = 0.0
    total_completeness = 0.0
    total_accuracy = 0.0
    errors = 0

    for case in TEST_CASES:
        company = case["input"]
        expected = case["expected"]

        try:
            raw_output = solve(company)
            brief = json.loads(raw_output)

            fmt = score_format(brief)
            comp = score_completeness(brief, expected.get("must_mention", []))
            acc = score_accuracy(brief, expected)

            case_score = 0.3 * fmt + 0.3 * comp + 0.4 * acc

            results.append({
                "company": company,
                "score": round(case_score, 4),
                "format": round(fmt, 4),
                "completeness": round(comp, 4),
                "accuracy": round(acc, 4),
                "verdict_got": brief.get("verdict"),
                "verdict_expected": expected.get("verdict"),
            })

            total_format += fmt
            total_completeness += comp
            total_accuracy += acc

        except Exception as exc:
            errors += 1
            results.append({
                "company": company,
                "score": 0.0,
                "error": str(exc),
            })

    n = len(TEST_CASES)
    avg_format = total_format / n
    avg_completeness = total_completeness / n
    avg_accuracy = total_accuracy / n
    final_score = 0.3 * avg_format + 0.3 * avg_completeness + 0.4 * avg_accuracy

    return {
        "score": round(final_score, 4),
        "details": {
            "n_cases": n,
            "errors": errors,
            "avg_format": round(avg_format, 4),
            "avg_completeness": round(avg_completeness, 4),
            "avg_accuracy": round(avg_accuracy, 4),
            "per_case": results,
        },
    }


if __name__ == "__main__":
    result = run_evaluation()
    print(json.dumps(result))
