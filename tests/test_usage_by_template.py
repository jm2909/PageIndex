"""User Story 1 (Phase 2): token usage recorded per prompt template (FR-001, FR-002, SC-001)."""
import json
import sys
from pathlib import Path

import pytest

from conftest import build_pdf
from fake_llm import FakeLLM
from pageindex.page_index_classic import page_index_main
from pageindex.utils import ConfigLoader, _llm_usage, _llm_usage_by_template, llm_template

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "markdown"
FIELDS = ("prompt_tokens", "completion_tokens", "cached_tokens", "cache_write_tokens")


@pytest.fixture(autouse=True)
def _in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def new_usage():
    return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
            "prompt_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
            "completion_tokens_details": {"reasoning_tokens": 0}}


def index_with_usage(doc, fake=None, **opt):
    fake = fake or FakeLLM()
    usage, by_template = new_usage(), {}
    token, by_token = _llm_usage.set(usage), _llm_usage_by_template.set(by_template)
    try:
        with fake.patched():
            page_index_main(str(doc), ConfigLoader().load({"model": "gpt-4o", **opt}))
    finally:
        _llm_usage.reset(token)
        _llm_usage_by_template.reset(by_token)
    usage["by_template"] = by_template  # test-local view
    return usage, fake


def totals(usage):
    return {"prompt_tokens": usage["prompt_tokens"],
            "completion_tokens": usage["completion_tokens"],
            "cached_tokens": usage["prompt_tokens_details"]["cached_tokens"],
            "cache_write_tokens": usage["prompt_tokens_details"]["cache_write_tokens"]}


def sections_doc(sections=6, words=200):
    words_list = "the index reads each page and builds a tree of sections".split()
    parts = []
    for s in range(sections):
        body = " ".join(words_list[(s + i) % len(words_list)] for i in range(words))
        parts.append(f"## Section {s + 1}\n\n" + "\n".join(body[i:i + 90] for i in range(0, len(body), 90)) + "\n\n")
    return "".join(parts)


def assert_sums(usage, fake):
    by = usage["by_template"]
    for field in FIELDS:
        assert sum(t[field] for t in by.values()) == totals(usage)[field], field
    assert sum(t["calls"] for t in by.values()) == len(fake.calls)
    for name in set(fake.templates):
        expected = {"generate_toc_init": "outline_init",
                    "generate_toc_continue": "outline_continue"}.get(name, name)
        assert by[expected]["calls"] == fake.templates.count(name), name


@pytest.mark.parametrize("fmt", ["pdf", "markdown"])
def test_by_template_sums_equal_totals(fmt, tmp_path):
    text = sections_doc()
    if fmt == "markdown":
        doc = tmp_path / "doc.md"
        doc.write_text(text, encoding="utf-8")
        usage, fake = index_with_usage(doc, md_page_tokens=300, if_add_doc_description="yes")
    else:
        doc = tmp_path / "doc.pdf"
        pages = [[(72, 750 - 12 * i, 10, line) for i, line in enumerate(chunk.splitlines()) if line.strip()]
                 for chunk in text.split("\n\n## ")]
        doc.write_bytes(build_pdf(pages))
        usage, fake = index_with_usage(doc, if_add_doc_description="yes")
    assert usage["prompt_tokens"] > 0
    assert_sums(usage, fake)
    assert {"toc_detector", "outline_init", "check_title_appearance", "check_title_start",
            "doc_description"} <= set(usage["by_template"])


def test_fix_up_calls_counted(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text(sections_doc(), encoding="utf-8")
    usage, fake = index_with_usage(doc, fake=FakeLLM(verify_no_first=1), md_page_tokens=300)
    assert fake.templates.count("toc_index_fixer") >= 1
    assert usage["by_template"]["toc_index_fixer"]["calls"] == fake.templates.count("toc_index_fixer")
    assert_sums(usage, fake)


def test_unnamed_calls_go_to_other():
    fake = FakeLLM()
    by_template = {}
    token = _llm_usage_by_template.set(by_template)
    try:
        fake.completion("m", "Your job is to detect if there is a table of content provided in the given text.")
        with llm_template("toc_detector"):
            fake.completion("m", "Your job is to detect if there is a table of content provided in the given text.")
    finally:
        _llm_usage_by_template.reset(token)
    assert by_template["other"]["calls"] == 1
    assert by_template["toc_detector"]["calls"] == 1


def test_llm_template_restores_previous_name():
    from pageindex.utils import _llm_template
    with llm_template("outer"):
        with llm_template("inner"):
            assert _llm_template.get() == "inner"
        assert _llm_template.get() == "outer"
    assert _llm_template.get() is None


def test_prompts_unchanged_by_template_names():
    sys.path.insert(0, str(ROOT / "tests" / "tools"))
    import capture_pdf_baseline as baseline
    expected = json.loads(baseline.BASELINE_FILE.read_text())
    record = baseline.capture(drop_keys=("source_type",))
    assert record["templates"] == expected["templates"]
    assert record["prompt_hashes"] == expected["prompt_hashes"]
    assert record["output_hash"] == expected["output_hash"]


def test_usage_dict_shape_unchanged(tmp_path):
    """The per-template tally lives apart from usage, whose shape callers rely on."""
    doc = tmp_path / "doc.md"
    doc.write_text(sections_doc(), encoding="utf-8")
    usage, _ = index_with_usage(doc, md_page_tokens=300)
    usage.pop("by_template")  # the test-local view added above
    assert set(usage) == {"prompt_tokens", "completion_tokens", "total_tokens",
                          "prompt_tokens_details", "completion_tokens_details"}


def test_local_client_returns_usage_by_template(tmp_path):
    from pageindex import PageIndexLocalClient
    doc = tmp_path / "doc.md"
    doc.write_text(sections_doc(), encoding="utf-8")
    client = PageIndexLocalClient(index={"storage_path": str(tmp_path / "store")})
    with FakeLLM().patched():
        result = client.submit_document(str(doc))
    by = result["usage_by_template"]
    assert "by_template" not in result["usage"]
    assert by and sum(t["calls"] for t in by.values()) > 0
