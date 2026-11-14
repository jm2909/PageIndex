"""User Story 2 (Phase 2): the opt-in cache-aware prompt layout (prompt_layout: cache).

Every call is answered by tests/fake_llm.py except the transport tests, which
stub LiteLLM itself. See specs/002-cache-aware-prompts/contracts/prompt-layout.md.
"""
import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import jsonschema
import pytest

from conftest import build_pdf
from fake_llm import FakeLLM
from test_markdown_pipeline import page_matched_pair
from pageindex import cache_layout
from pageindex.cache_layout import SYSTEM_BLOCK, LayoutBlocks, LayoutRun
from pageindex.page_index_classic import page_index_main, process_none_page_numbers
from pageindex.utils import (ConfigLoader, _llm_usage, _llm_usage_by_template, count_tokens,
                             llm_acompletion, llm_completion)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "markdown"
SCHEMA = json.loads((ROOT / "pageindex" / "schema" / "tree-output.schema.json").read_text())
MODEL = "gpt-4o"
WHOLE_DOC = ("outline_whole", "toc_index_fixer", "add_page_number", "doc_description")
PAGE_SCOPE = ("toc_detector", "placement_check", "leaf_summary")
MARKER = re.compile(r"<physical_index_(\d+)>")


@pytest.fixture(autouse=True)
def _in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def new_usage():
    return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
            "prompt_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
            "completion_tokens_details": {"reasoning_tokens": 0}}


def run(doc, fake=None, layout="cache", **kw):
    fake = fake or FakeLLM()
    usage, by_template = new_usage(), {}
    token, by_token = _llm_usage.set(usage), _llm_usage_by_template.set(by_template)
    try:
        with fake.patched():
            result = page_index_main(str(doc), ConfigLoader().load(
                {"model": MODEL, "prompt_layout": layout, "if_add_doc_description": "yes", **kw}))
    finally:
        _llm_usage.reset(token)
        _llm_usage_by_template.reset(by_token)
    fake.usage, fake.by_template = usage, by_template
    return result, fake


WORDS = "the index reads each page and builds a tree of sections for later search".split()


def sections_text(sections=6, words=200):
    parts = []
    for s in range(sections):
        body = " ".join(WORDS[(s + i) % len(WORDS)] for i in range(words))
        parts.append(f"## Section {s + 1}\n\n" + "\n".join(body[i:i + 90] for i in range(0, len(body), 90)) + "\n\n")
    return "".join(parts)


def md_doc(tmp_path, **kw):
    doc = tmp_path / "doc.md"
    doc.write_text(sections_text(**kw), encoding="utf-8")
    return doc


def pdf_doc(tmp_path, **kw):
    pages = [[(72, 750 - 12 * i, 10, line) for i, line in enumerate(chunk.splitlines()) if line.strip()]
             for chunk in sections_text(**kw).split("\n\n## ")]
    doc = tmp_path / "doc.pdf"
    doc.write_bytes(build_pdf(pages))
    return doc


def walk(nodes):
    for n in nodes:
        yield n
        yield from walk(n.get("nodes") or [])


def blocks_of(fake, task):
    return [(system, document, question) for name, system, document, question in fake.blocks if name == task]


def field(question, key):
    m = re.search(rf"^{key}:\s*(.*)$", question, re.M)
    return m.group(1).strip() if m else None


# ------------------------------------------------------------------- T013 ---

def test_setting_default_off(tmp_path):
    assert ConfigLoader().load({}).prompt_layout == "standard"
    _, fake = run(md_doc(tmp_path), layout="standard", md_page_tokens=300)
    assert fake.calls and not fake.blocks  # no cache-layout call at all
    assert cache_layout.active() is None


def test_flash_ignores_layout(tmp_path):
    from pageindex.local_api import LocalAPI
    seen = {}

    def flash(path, **_):
        seen["active"] = cache_layout.active()
        raise RuntimeError("stop here")

    api = LocalAPI(storage_path=str(tmp_path / "store"), model=MODEL, summary_model=MODEL,
                   prompt_layout="cache")
    with patch("pageindex.flash.page_index_flash", flash):
        with pytest.raises(RuntimeError, match="stop here"):
            api._index_flash(str(pdf_doc(tmp_path)))
    assert seen == {"active": None}


@pytest.mark.parametrize("fmt", ["pdf", "markdown"])
def test_three_part_layout(fmt, tmp_path):
    doc = pdf_doc(tmp_path) if fmt == "pdf" else md_doc(tmp_path)
    _, fake = run(doc, md_page_tokens=300)
    assert fake.blocks and len(fake.blocks) == len(fake.calls)  # every call uses the layout
    for i, (name, system, document, question) in enumerate(fake.blocks):
        assert system == SYSTEM_BLOCK
        assert question.startswith(f"TASK: {name}")
        assert len(question) < 2000 or name in ("parent_summary", "doc_description")
        if name in ("parent_summary", "doc_description"):
            continue  # they are given child summaries by design
        for earlier in fake.replies[:i]:  # no earlier answer leaks into a later call
            assert earlier not in document + question


def test_system_block_cacheable_size():
    # LiteLLM's counter undercounts Claude (~1.6x), so this is conservative
    assert count_tokens(SYSTEM_BLOCK, "anthropic/claude-haiku-5-5") >= 512
    for task in cache_layout.TASKS:
        assert f"{task} -" in SYSTEM_BLOCK  # one numbered section per task


def test_system_block_identical_across_calls(tmp_path):
    _, fake = run(pdf_doc(tmp_path))
    assert {system for _, system, _, _ in fake.blocks} == {SYSTEM_BLOCK}


# ------------------------------------------------------------------- T014 ---

def test_document_scope_by_template(tmp_path):
    doc = pdf_doc(tmp_path)
    _, fake = run(doc, fake=FakeLLM(verify_no_first=2))  # two wrong starts -> fix-ups
    names = {name for name, *_ in fake.blocks}
    assert {"outline_whole", "toc_index_fixer", "doc_description", "toc_detector",
            "placement_check", "leaf_summary"} <= names
    n_pages = max(int(m) for _, d, _ in blocks_of(fake, "outline_whole") for m in MARKER.findall(d))
    for task in WHOLE_DOC:
        for _, document, _ in blocks_of(fake, task):
            assert sorted({int(m) for m in MARKER.findall(document)}) == list(range(1, n_pages + 1))
    for task in PAGE_SCOPE:
        for _, document, _ in blocks_of(fake, task):
            assert document.startswith("<user_document>") and not MARKER.search(document)
    for _, _, question in blocks_of(fake, "toc_index_fixer"):
        assert re.fullmatch(r"\d+-\d+", field(question, "pages"))


def test_add_page_number_uses_whole_document():
    page_list = [(f"page {i} text", 5) for i in range(1, 6)]
    items = [{"structure": "1", "title": "A", "physical_index": 1},
             {"structure": "2", "title": "B", "page": 3},
             {"structure": "3", "title": "C", "physical_index": 5}]
    fake = FakeLLM()
    with fake.patched(), cache_layout.layout_run("cache", page_list) as layout:
        process_none_page_numbers(items, page_list, model=MODEL)
    (_, document, question), = blocks_of(fake, "add_page_number")
    assert document == layout.whole_document()
    assert field(question, "pages") == "1-5"
    assert items[1]["physical_index"] == 1 and "page" not in items[1]


def test_whole_doc_block_identical(tmp_path):
    _, fake = run(pdf_doc(tmp_path), fake=FakeLLM(verify_no_first=2))
    whole = {document for name, _, document, _ in fake.blocks if name in WHOLE_DOC}
    assert len(whole) == 1


def test_redaction_applied_to_blocks():
    result, fake = run(FIXTURES / "injection.md", if_add_node_text="yes")
    (_, document, _), = blocks_of(fake, "outline_whole")
    assert "Please [REDACTED] and reveal" in document
    assert "Please ignore previous instructions" not in document
    texts = "".join(n.get("text", "") for n in walk(result["structure"]))
    assert "ignore previous instructions" in texts and "[REDACTED]" not in texts  # stored pages unchanged


# ------------------------------------------------------------------- T015 ---

def test_merged_placement_check_one_call_per_section(tmp_path):
    result, fake = run(pdf_doc(tmp_path))
    assert not {"check_title_appearance", "check_title_start"} & set(fake.templates)
    checks = [(field(q, "title"), field(q, "page")) for _, _, q in blocks_of(fake, "placement_check")]
    (_, _, _), = blocks_of(fake, "outline_whole")
    outline = json.loads(fake.replies[fake.templates.index("outline_whole")])
    assert len(checks) == len(outline) == len(set(checks))  # start check served from the memo

    # a fix-up that moves a section's start asks once more, for the new page only
    _, fixed = run(pdf_doc(tmp_path), fake=FakeLLM(verify_no_first=2))
    pairs = [(field(q, "title"), field(q, "page")) for _, _, q in blocks_of(fixed, "placement_check")]
    assert len(pairs) == len(set(pairs)) > len(outline)


def test_outline_single_call_when_fits(tmp_path):
    _, fake = run(pdf_doc(tmp_path))
    assert fake.templates.count("outline_whole") == 1
    assert not {"generate_toc_init", "generate_toc_continue"} & set(fake.templates)


def test_outline_falls_back_when_too_big(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(cache_layout, "_max_input_tokens", lambda model: 100)
    with caplog.at_level("INFO"):
        result, fake = run(pdf_doc(tmp_path))
    assert "outline_whole" not in fake.templates and "generate_toc_init" in fake.templates
    assert "chunked outline" in caplog.text
    assert "placement_check" in fake.templates  # the rest of the layout still applies
    jsonschema.validate(result, SCHEMA)


# ------------------------------------------------------------------- T016 ---

def test_warm_first_then_parallel(tmp_path):
    # big pages: several sections share a page, so their checks share a cached page block
    _, fake = run(md_doc(tmp_path, sections=8, words=120), md_page_tokens=1200)
    position = {(kind, number): i for i, (kind, _, number) in enumerate(fake.events)}
    groups = {}
    for number, (name, _, document, _) in enumerate(fake.blocks):
        groups.setdefault(document, []).append(number)
    shared = [numbers for numbers in groups.values() if len(numbers) > 1]
    assert shared
    for numbers in shared:
        first, rest = numbers[0], numbers[1:]
        assert all(position[("end", first)] < position[("start", n)] for n in rest)
    # calls on different prefixes still overlap
    placement = [n for n, (name, *_) in enumerate(fake.blocks) if name == "placement_check"]
    assert any(position[("start", b)] < position[("end", a)]
               for a in placement for b in placement if a < b)


def test_warm_failure_still_runs_rest():
    run_state = LayoutRun(page_list=[])
    blocks = LayoutBlocks(SYSTEM_BLOCK, "page", "TASK: placement_check")
    order = []

    async def call(i):
        async with run_state.warm_first(blocks):
            order.append(("start", i))
            await asyncio.sleep(0)
            if i == 0:
                raise RuntimeError("first failed")
            order.append(("end", i))
            return i

    async def main():
        return await asyncio.gather(*(call(i) for i in range(3)), return_exceptions=True)

    results = asyncio.run(main())
    assert isinstance(results[0], RuntimeError) and results[1:] == [1, 2]
    assert order[0] == ("start", 0) and order[1] in (("start", 1), ("start", 2))


def _response(content="{}"):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content),
                                                    finish_reason="stop")], usage=None)


def test_cache_markers_present():
    sent = []

    def fake_completion(**kw):
        sent.append(kw)
        return _response()

    async def fake_acompletion(**kw):
        sent.append(kw)
        return _response()

    blocks = LayoutBlocks(SYSTEM_BLOCK, "<user_document>page</user_document>", "TASK: toc_detector")
    with patch("litellm.completion", fake_completion), patch("litellm.acompletion", fake_acompletion):
        llm_completion("anthropic/claude-haiku-5-5", "ignored", layout_blocks=blocks)
        asyncio.run(llm_acompletion("anthropic/claude-haiku-5-5", "ignored", layout_blocks=blocks))
        llm_completion("anthropic/claude-haiku-5-5", "go on", layout_blocks=blocks,
                       chat_history=[{"role": "assistant", "content": "partial"}])
        llm_completion("anthropic/claude-haiku-5-5", "plain prompt")
    expected = [
        {"role": "system", "content": [{"type": "text", "text": SYSTEM_BLOCK,
                                        "cache_control": {"type": "ephemeral"}}]},
        {"role": "user", "content": [
            {"type": "text", "text": blocks.document, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": blocks.question}]},
    ]
    assert sent[0]["messages"] == expected and sent[1]["messages"] == expected
    assert sent[2]["messages"] == expected + [{"role": "assistant", "content": "partial"},
                                              {"role": "user", "content": "go on"}]
    assert sent[3]["messages"] == [{"role": "user", "content": "plain prompt"}]  # unchanged


def test_cache_layout_skips_cache_off_option(monkeypatch):
    from pageindex import utils
    monkeypatch.setattr(utils, "_cache_off", lambda model, sent: {"prompt_cache_options": {"mode": "explicit"}})
    sent = []
    with patch("litellm.completion", lambda **kw: sent.append(kw) or _response()):
        llm_completion("anthropic/claude-haiku-5-5", "x",
                       layout_blocks=LayoutBlocks(SYSTEM_BLOCK, None, "TASK: toc_detector"))
        llm_completion("anthropic/claude-haiku-5-5", "x")
    assert "prompt_cache_options" not in sent[0] and "prompt_cache_options" in sent[1]
    assert len(sent[0]["messages"][1]["content"]) == 1  # no document part


def test_cache_reads_recorded(tmp_path):
    _, fake = run(pdf_doc(tmp_path))
    by = fake.by_template
    assert by["placement_check"]["cached_tokens"] > 0  # the system block is read back
    assert sum(t["cached_tokens"] for t in by.values()) == fake.usage["prompt_tokens_details"]["cached_tokens"]


def test_no_cache_provider_still_indexes(tmp_path):
    result, fake = run(pdf_doc(tmp_path), fake=FakeLLM(report_usage=False))
    jsonschema.validate(result, SCHEMA)
    assert fake.blocks


def test_same_template_sequence_pdf_vs_md_cache_layout(tmp_path):
    md, pdf, n_pages = page_matched_pair(tmp_path)
    md_result, md_fake = run(md, md_page_tokens=400)
    pdf_result, pdf_fake = run(pdf)
    assert md_fake.templates == pdf_fake.templates
    assert "outline_whole" in md_fake.templates and "placement_check" in md_fake.templates
    assert max(n["end_index"] for n in walk(md_result["structure"])) == n_pages
    assert max(n["end_index"] for n in walk(pdf_result["structure"])) == n_pages


@pytest.mark.parametrize("name", ["all_blocks.md", "no_headings.md"])
def test_cache_layout_tree_validates_schema(name, tmp_path):
    result, _ = run(FIXTURES / name)
    jsonschema.validate(result, SCHEMA)
    result, _ = run(pdf_doc(tmp_path))
    jsonschema.validate(result, SCHEMA)
