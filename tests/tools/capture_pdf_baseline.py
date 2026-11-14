"""Record the PDF standard-mode baseline (mocked LLM) before the Markdown work.

Usage (from the repo root):  python tests/tools/capture_pdf_baseline.py

Writes tests/data/pdf_baseline/baseline.json holding only prompt-template names
and SHA-256 hashes: no document text enters the repo (Constitution VI).
test_markdown_pipeline.py::test_pdf_unchanged replays the same capture and
compares.
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

BASELINE_PDF = ROOT / "examples" / "documents" / "2023-annual-report-truncated.pdf"
BASELINE_FILE = ROOT / "tests" / "data" / "pdf_baseline" / "baseline.json"
MODEL = "gpt-4o"


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def capture(drop_keys=(), return_result=False):
    """Index the baseline PDF with the fake LLM; return the hash record (and
    the raw result with ``return_result``)."""
    from fake_llm import FakeLLM
    from pageindex.page_index_classic import page_index_main
    from pageindex.utils import ConfigLoader

    fake = FakeLLM()
    cwd = os.getcwd()
    tmp = tempfile.mkdtemp()
    os.chdir(tmp)  # JsonLogger writes ./logs
    try:
        with fake.patched():
            result = page_index_main(str(BASELINE_PDF), ConfigLoader().load({"model": MODEL}))
    finally:
        os.chdir(cwd)
        shutil.rmtree(tmp, ignore_errors=True)
    raw = result
    result = {k: v for k, v in result.items() if k not in drop_keys}
    # prompt hashes are compared as a sorted multiset; the template list keeps
    # the call order
    record = {
        "pdf": BASELINE_PDF.name,
        "templates": fake.templates,
        "prompt_hashes": sorted(sha256(p) for _, p in fake.calls),
        "output_hash": sha256(canonical(result)),
    }
    return (record, raw) if return_result else record


if __name__ == "__main__":
    record = capture()
    BASELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_FILE.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {BASELINE_FILE} ({len(record['templates'])} calls)")
