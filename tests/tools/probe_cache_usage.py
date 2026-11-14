"""One-off live probe (T004): how does LiteLLM report Anthropic prompt-cache usage?

Sends the same >512-token system block twice with cache_control and prints the
usage fields of both replies (numbers and field names only, never the key).
Spends a tiny amount of real API tokens; never run by pytest.

Usage (from PageIndex/):  .venv/bin/python tests/tools/probe_cache_usage.py
Reads `model` and `API_KEY` from ../.env (the workspace .env).
"""
import json
import os
import sys
from pathlib import Path

ENV = Path(__file__).resolve().parents[3] / ".env"


def load_env():
    values = {}
    for line in ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip().strip('"').strip("'")
    os.environ["ANTHROPIC_API_KEY"] = values["API_KEY"]
    model = values["model"]
    return model if "/" in model else f"anthropic/{model}"


def usage_fields(usage):
    data = usage.model_dump() if hasattr(usage, "model_dump") else dict(usage)
    keep = {}
    for key, value in data.items():
        if isinstance(value, dict):
            keep[key] = {k: v for k, v in value.items() if v not in (None, 0, {}, [])}
        elif value not in (None, {}, []):
            keep[key] = value
    return keep


def main():
    import litellm
    model = load_env()
    system = ("You index documents. " + "Rule: answer in JSON only, never prose. " * 220).strip()
    messages = [
        {"role": "system", "content": [{"type": "text", "text": system,
                                        "cache_control": {"type": "ephemeral"}}]},
        {"role": "user", "content": "Reply with {\"ok\": true}."},
    ]
    print(f"model: {model}; system block tokens ≈ {litellm.token_counter(model=model, text=system)}")
    for attempt in (1, 2):
        reply = litellm.completion(model=model, messages=messages, max_tokens=20)
        print(f"\n--- call {attempt} usage ---")
        print(json.dumps(usage_fields(reply.usage), indent=2, default=str))


if __name__ == "__main__":
    sys.exit(main())
