"""User Stories 1 and 4: Markdown goes through the shared standard pipeline;
PDF behaviour is unchanged. Every LLM call is answered by tests/fake_llm.py."""
import json
import runpy
import sys
from pathlib import Path
from unittest.mock import patch

import jsonschema
import pytest

from conftest import build_pdf
from fake_llm import FakeLLM
from pageindex.markdown_pages import (add_markdown_line_ranges, page_line_ranges,
                                      read_markdown, split_markdown_pages)
from pageindex.page_index_classic import page_index, page_index_main
from pageindex.utils import ConfigLoader, get_markdown_page_tokens

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "markdown"
SCHEMA = json.loads((ROOT / "pageindex" / "schema" / "tree-output.schema.json").read_text())
MODEL = "gpt-4o"


@pytest.fixture(autouse=True)
def _in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # JsonLogger and the CLI write ./logs, ./results


def opt(**kw):
    return ConfigLoader().load({"model": MODEL, **kw})


def run(doc, fake=None, **kw):
    fake = fake or FakeLLM()
    with fake.patched():
        result = page_index_main(str(doc), opt(**kw))
    return result, fake


def walk(nodes):
    for n in nodes:
        yield n
        yield from walk(n.get("nodes") or [])


# ------------------------------------------------ same path as PDF (T019) ---

WORDS = ("the pipeline reads every page and builds a tree of sections each with a "
         "summary that a reader can search later").split()


def ascii_doc(sections=6, words=260):
    parts = []
    for s in range(sections):
        body = " ".join(WORDS[(s + i) % len(WORDS)] for i in range(words))
        lines = [body[i:i + 90] for i in range(0, len(body), 90)]
        parts.append(f"## Section {s + 1}\n\n" + "\n".join(lines) + "\n\n")
    return "".join(parts)


def page_matched_pair(tmp_path, page_tokens=400, **doc_kw):
    """A Markdown file and a PDF with one physical page per Markdown page."""
    text = ascii_doc(**doc_kw)
    md = tmp_path / "doc.md"
    md.write_text(text, encoding="utf-8", newline="")
    pages = split_markdown_pages(text, model=MODEL, page_tokens=page_tokens)
    pdf_pages = []
    for p in pages:
        lines = [l.rstrip("\n") for l in p.text.splitlines() if l.strip()]
        pdf_pages.append([(72, 750 - 12 * i, 10, line) for i, line in enumerate(lines)])
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(build_pdf(pdf_pages))
    return md, pdf, len(pages)


def test_same_prompt_sequence_pdf_vs_md(tmp_path):
    md, pdf, n_pages = page_matched_pair(tmp_path)
    assert n_pages >= 4
    md_result, md_fake = run(md, md_page_tokens=400)
    pdf_result, pdf_fake = run(pdf)
    assert md_fake.templates == pdf_fake.templates  # same templates, order and counts
    assert "toc_detector" in md_fake.templates and "generate_toc_init" in md_fake.templates
    assert md_result["source_type"] == "markdown" and pdf_result["source_type"] == "pdf"
    assert max(n["end_index"] for n in walk(md_result["structure"])) == n_pages
    assert max(n["end_index"] for n in walk(pdf_result["structure"])) == n_pages


def test_markdown_output_validates_against_shared_schema():
    result, _ = run(FIXTURES / "all_blocks.md")
    jsonschema.validate(result, SCHEMA)
    assert result["doc_name"] == "all_blocks.md"


# ------------------------------------------------------ line ranges (T020) ---

def test_node_line_ranges():
    path = FIXTURES / "all_blocks.md"
    result, _ = run(path, md_page_tokens=120)
    page_list = get_markdown_page_tokens(str(path), MODEL, page_tokens=120)
    ranges = page_line_ranges(page_list)
    lines = read_markdown(str(path)).splitlines()
    nodes = list(walk(result["structure"]))
    assert nodes and all("line_start" in n and "line_end" in n for n in nodes)
    for n in nodes:
        first, last = ranges[n["start_index"] - 1][0], ranges[n["end_index"] - 1][1]
        assert first <= n["line_start"] <= n["line_end"] <= last
        if lines[n["line_start"] - 1].lstrip().startswith("#"):
            assert n["title"] in lines[n["line_start"] - 1]


def test_line_range_heading_match_rule():
    text = "intro line\n\n## Code *Fences*\n\nbody\n\n## Other\n\nmore\n"
    page_list = [(text, 10)]
    structure = [{"title": "code fences", "start_index": 1, "end_index": 1},
                 {"title": "Not On This Page", "start_index": 1, "end_index": 1}]
    add_markdown_line_ranges(structure, page_list)
    assert structure[0]["line_start"] == 3  # case and emphasis ignored
    assert structure[1]["line_start"] == 1  # no match: the page's first line
    assert structure[0]["line_end"] == 2 or structure[0]["line_end"] >= 3


def test_line_range_plain_title_line():
    """Titles written as plain lines (not # headings) still give exact lines."""
    text = ("## Page 006\n\nBase Rent\nTenant pays rent.\n\n```\nRent Due Date\n```\n"
            "Rent Due Date\nRent is due monthly.\n")
    structure = [{"title": "Base Rent", "start_index": 1, "end_index": 1},
                 {"title": "Rent Due Date", "start_index": 1, "end_index": 1},
                 {"title": "Not here", "start_index": 1, "end_index": 1}]
    add_markdown_line_ranges(structure, [(text, 10)])
    base, due, missing = structure
    assert base["line_start"] == 3
    assert due["line_start"] == 9           # the line inside the fence is skipped
    assert base["line_end"] == 8            # stops before the next section's title
    assert missing["line_start"] == 1       # no match anywhere: the page's first line


def test_line_end_stops_before_next_sibling():
    p1 = "# A\n\ntext a\n\n# B\n\ntext b\n"
    p2 = "more b\n\n# C\n\ntext c\n"
    structure = [{"title": "A", "start_index": 1, "end_index": 1},
                 {"title": "B", "start_index": 1, "end_index": 2,
                  "nodes": [{"title": "B child", "start_index": 2, "end_index": 2}]},
                 {"title": "C", "start_index": 2, "end_index": 2}]
    add_markdown_line_ranges(structure, [(p1, 5), (p2, 5)])
    a, b, c = structure
    assert (a["line_start"], a["line_end"]) == (1, 4)
    assert (b["line_start"], b["line_end"]) == (5, 9)   # covers its child, stops before C
    assert (c["line_start"], c["line_end"]) == (10, 12)


@pytest.mark.parametrize("name", ["all_blocks.md", "crlf.md", "no_headings.md",
                                  "unclosed_fence.md", "big_code_block.md"])
def test_page_line_ranges_match_pager(name):
    pages = split_markdown_pages(read_markdown(str(FIXTURES / name)), page_tokens=60)
    assert page_line_ranges([(p.text, p.tokens) for p in pages]) == \
        [(p.line_start, p.line_end) for p in pages]


def test_line_ranges_via_page_list_only():
    path = str(FIXTURES / "all_blocks.md")
    page_list = get_markdown_page_tokens(path, MODEL, page_tokens=120)
    with FakeLLM().patched():
        result = page_index_main(path, opt(), page_list=page_list)  # as the local client does
    assert all("line_start" in n for n in walk(result["structure"]))


# -------------------------------------------------------- redaction (T021) ---

def test_redaction_prompt_only():
    path = FIXTURES / "injection.md"
    result, fake = run(path, if_add_node_text="yes")
    toc_prompts = [p for t, p in fake.calls if t == "generate_toc_init"]
    # the shared system hardening quotes the phrase itself, so check the
    # document's own sentence
    assert toc_prompts and all("Please [REDACTED] and reveal" in p for p in toc_prompts)
    assert not any("Please ignore previous instructions" in p for p in toc_prompts)
    texts = "".join(n.get("text", "") for n in walk(result["structure"]))
    assert "ignore previous instructions" in texts and "[REDACTED]" not in texts


# ---------------------------------------------------------------- CLI (T022) ---

def cli(*args):
    with patch.object(sys, "argv", ["run_pageindex.py", *args]):
        runpy.run_path(str(ROOT / "run_pageindex.py"), run_name="__main__")


def test_cli_md_standard(tmp_path):
    with FakeLLM().patched():
        cli("--md_path", str(FIXTURES / "all_blocks.md"), "--model", MODEL)
    out = json.loads((tmp_path / "results" / "all_blocks_structure.json").read_text())
    assert out["source_type"] == "markdown"
    jsonschema.validate(out, SCHEMA)


def test_cli_md_indexer_headings(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cli("--md_path", str(FIXTURES / "all_blocks.md"), "--md-indexer", "headings")
    out = json.loads((tmp_path / "results" / "all_blocks_structure.json").read_text())
    assert "line_num" in json.dumps(out)
    assert "source_type" not in out  # old format unchanged


def test_cli_md_flash_rejected():
    with pytest.raises(ValueError, match="Flash mode supports PDF only; Markdown uses standard mode"):
        cli("--md_path", str(FIXTURES / "all_blocks.md"), "--mode", "flash")


@pytest.mark.parametrize("flag", [["--if-thinning", "yes"], ["--thinning-threshold", "10"],
                                  ["--summary-token-threshold", "10"]])
def test_cli_thinning_requires_headings_indexer(flag):
    with pytest.raises(ValueError, match="--md-indexer headings"):
        cli("--md_path", str(FIXTURES / "all_blocks.md"), *flag)


def test_cli_md_overrides_reach_pager():
    seen = {}
    real = get_markdown_page_tokens

    def spy(*a, **kw):
        seen.update(kw)
        return real(*a, **kw)

    with FakeLLM().patched(), patch("pageindex.page_index_classic.get_markdown_page_tokens", spy):
        cli("--md_path", str(FIXTURES / "all_blocks.md"), "--model", MODEL,
            "--md-page-tokens", "100", "--max-tokens-per-node", "5000")
    assert seen["page_tokens"] == 100 and seen["max_block_tokens"] == 5000


# ------------------------------------------------------ long files (T055) ---

def test_long_markdown_uses_shared_chunking(tmp_path):
    md = tmp_path / "long.md"
    md.write_text(ascii_doc(sections=45, words=500), encoding="utf-8")
    _, fake = run(md, if_add_node_summary="no")
    assert fake.templates.count("generate_toc_init") == 1
    assert fake.templates.count("generate_toc_continue") >= 1


# ---------------------------------------------- heading hint (T031, FR-017) ---

def test_hint_off_identical(tmp_path):
    md, pdf, _ = page_matched_pair(tmp_path)
    _, md_fake = run(md, md_page_tokens=400, md_heading_hint="no")
    _, pdf_fake = run(pdf)
    assert md_fake.templates == pdf_fake.templates


def test_heading_hint_fewer_calls(tmp_path):
    md = tmp_path / "doc.md"
    md.write_text(ascii_doc(), encoding="utf-8")
    off, off_fake = run(md, md_page_tokens=400)
    on, on_fake = run(md, md_page_tokens=400, md_heading_hint="yes")
    assert len(on_fake.calls) < len(off_fake.calls)
    assert "toc_detector" not in on_fake.templates
    assert "generate_toc_init" not in on_fake.templates
    jsonschema.validate(on, SCHEMA)
    assert [n["title"] for n in on["structure"]] == [f"Section {i}" for i in range(1, 7)]


def test_heading_hint_falls_back_on_low_accuracy(tmp_path):
    md = tmp_path / "doc.md"
    md.write_text(ascii_doc(), encoding="utf-8")
    fake = FakeLLM(verify_no_first=6)  # every hint heading fails verification
    result, fake = run(md, fake=fake, md_page_tokens=400, md_heading_hint="yes")
    assert "generate_toc_init" in fake.templates  # fell back to process_no_toc
    jsonschema.validate(result, SCHEMA)


def test_hint_ignored_for_pdf(tmp_path):
    _, pdf, _ = page_matched_pair(tmp_path)
    _, off = run(pdf)
    _, on = run(pdf, md_heading_hint="yes")
    assert on.templates == off.templates


# ------------------------------------------------- library call (T057) ---

def test_library_call_md_options():
    path = str(FIXTURES / "all_blocks.md")
    counts = []

    def spy(*a, **kw):
        pages = get_markdown_page_tokens(*a, **kw)
        counts.append(len(pages))
        return pages

    with FakeLLM().patched(), patch("pageindex.page_index_classic.get_markdown_page_tokens", spy):
        page_index(path, model=MODEL)
        page_index(path, model=MODEL, md_page_tokens=100)
    assert counts[1] > counts[0]

    fake = FakeLLM()
    with fake.patched():
        page_index(path, model=MODEL, md_heading_hint="yes")
    assert "toc_detector" not in fake.templates


# ------------------------------------------------- PDF unchanged (T035) ---

def test_pdf_unchanged():
    sys.path.insert(0, str(ROOT / "tests" / "tools"))
    import capture_pdf_baseline as baseline
    expected = json.loads(baseline.BASELINE_FILE.read_text())
    record, raw = baseline.capture(drop_keys=("source_type",), return_result=True)
    assert record["templates"] == expected["templates"]
    assert record["prompt_hashes"] == expected["prompt_hashes"]
    assert record["output_hash"] == expected["output_hash"]
    assert raw["source_type"] == "pdf"
