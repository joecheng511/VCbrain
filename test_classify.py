"""Temporary debug script — delete after use."""
import sys, os
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv()

from google import genai
from google.genai import types as genai_types
from app.routes.chat import _CLASSIFIER_SYSTEM

model_name = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
print(f"Using model: {model_name!r}\n")
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

for msg in [
    "What is our healthcare exposure?",
    "What is the current state of our fund?",
    "Compare Hogan PLC and Parker Group",
    "What conflicts need attention?",
]:
    resp = client.models.generate_content(
        model=model_name,
        contents=f'User question: {msg!r}',
        config=genai_types.GenerateContentConfig(
            system_instruction=_CLASSIFIER_SYSTEM,
            max_output_tokens=300,
        ),
    )
    print(f"Q: {msg}")
    print(f"  raw:    {resp.text!r}")
    if resp.candidates:
        c = resp.candidates[0]
        print(f"  finish: {c.finish_reason}")
        print(f"  tokens: input={resp.usage_metadata.prompt_token_count if resp.usage_metadata else '?'} "
              f"output={resp.usage_metadata.candidates_token_count if resp.usage_metadata else '?'}")
    print()
