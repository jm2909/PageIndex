"""User Story 2: the Markdown pager is lossless and block-aware (FR-003..FR-006, FR-014)."""
import logging
import re
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from pageindex.markdown_pages import (MarkdownPage, read_markdown, scan_markdown,
                                      split_lines, split_markdown_pages)

FIXTURES = Path(__file__).parent / "fixtures" / "markdown"
SPLITTABLE = ["all_blocks.md", "no_headings.md", "crlf.md", "unclosed_fence.md",
              "big_code_block.md", "huge_block.md", "injection.md"]


def pages_of(name, **kw):
    return split_markdown_pages(read_markdown(str(FIXTURES / name)), **kw)


@pytest.mark.parametrize("name", SPLITTABLE)
@pytest.mark.parametrize("page_tokens", [50, 800])
def test_lossless_round_trip(name, page_tokens):
    text = read_markdown(str(FIXTURES / name))
    pages = split_markdown_pages(text, page_tokens=page_tokens)
    assert "".join(p.text for p in pages) == text
    # byte for byte against the file on disk too
    assert "".join(p.text for p in pages).encode("utf-8") == (FIXTURES / name).read_bytes()
    assert [p.page_index for p in pages] == list(range(1, len(pages) + 1))
    assert all(isinstance(p, MarkdownPage) for p in pages)


def _protected_ranges(text):
    """(first, last) 0-based line indices of every protected block."""
    scan = scan_markdown(split_lines(text))
    return scan.blocks


def _break_lines(pages):
    """0-based index of the first line of every page after the first."""
    return [p.line_start - 1 for p in pages[1:]]


def test_no_break_inside_protected_blocks():
    text = read_markdown(str(FIXTURES / "all_blocks.md"))
    pages = split_markdown_pages(text, page_tokens=50)
    assert len(pages) > 5, "small budget should force many breaks"
    blocks = _protected_ranges(text)
    kinds = {kind for kind, _, _ in blocks}
    assert {"front_matter", "fence", "table", "list", "blockquote", "html", "setext"} <= kinds
    for brk in _break_lines(pages):
        for kind, first, last in blocks:
            assert not (first < brk <= last), f"break before line {brk + 1} inside {kind} {first + 1}-{last + 1}"


def test_unclosed_fence_runs_to_end_of_file():
    lines = split_lines(read_markdown(str(FIXTURES / "unclosed_fence.md")))
    fences = [(a, b) for kind, a, b in scan_markdown(lines).blocks if kind == "fence"]
    assert fences == [(4, len(lines) - 1)]


def test_front_matter_only_at_top():
    lines = split_lines("intro\n\n---\nnot: front matter\n---\n")
    assert not [b for b in scan_markdown(lines).blocks if b[0] == "front_matter"]


def test_budget_and_preferred_breaks():
    text = read_markdown(str(FIXTURES / "all_blocks.md"))
    budget = 120
    pages = split_markdown_pages(text, page_tokens=budget)
    lines = split_lines(text)
    scan = scan_markdown(lines)
    heading_lines = {h.line for h in scan.headings}
    for p in pages:
        if p.tokens > budget:
            # only one unbreakable unit (a protected block, a single line, or a
            # heading with its first line, plus attached blank lines) may
            # exceed the budget: no allowed break point inside the page
            inner = range(p.line_start, p.line_end)  # 0-based lines after the first
            assert all(scan.no_break_before[k] for k in inner), p
    # breaks land before a heading or after a blank line wherever possible
    preferred = 0
    for brk in _break_lines(pages):
        if brk in heading_lines or not lines[brk - 1].strip():
            preferred += 1
    assert preferred >= len(pages[1:]) * 0.6


def test_breaks_prefer_headings():
    doc = "".join(f"## Section {i}\n\n" + "word " * 60 + "\n\n" for i in range(8))
    pages = split_markdown_pages(doc, page_tokens=150)
    assert len(pages) > 2
    assert all(p.text.startswith("## Section") for p in pages)


def test_oversized_block_warning(caplog):
    big = pages_of("big_code_block.md")
    fence_pages = [p for p in big if "```text" in p.text]
    assert len(fence_pages) == 1 and fence_pages[0].tokens > 800
    assert "```\n" in fence_pages[0].text.split("```text", 1)[1], "fence kept whole"

    with caplog.at_level(logging.WARNING):
        huge = pages_of("huge_block.md")
    assert any("oversized" in r.message for r in caplog.records)
    assert len(huge) > 2
    assert all(p.tokens <= 20000 for p in huge)


def test_cut_threshold_follows_max_tokens_per_node(caplog):
    with caplog.at_level(logging.WARNING):
        pages = pages_of("big_code_block.md", max_block_tokens=1000)
    assert any("oversized" in r.message for r in caplog.records)
    assert all(p.tokens <= 1000 for p in pages)


@pytest.mark.parametrize("name", SPLITTABLE)
def test_line_ranges(name):
    text = read_markdown(str(FIXTURES / name))
    pages = split_markdown_pages(text, page_tokens=60)
    total = len(split_lines(text))
    assert pages[0].line_start == 1
    for a, b in zip(pages, pages[1:]):
        assert a.line_end + 1 == b.line_start
    assert pages[-1].line_end == total
    for p in pages:
        assert len(split_lines(p.text)) == p.line_end - p.line_start + 1


def test_crlf_line_counting():
    text = read_markdown(str(FIXTURES / "crlf.md"))
    assert "\r\n" in text and re.search(r"[^\r]\n", text), "fixture mixes endings"
    # an editor counts lines on \r\n, \n and \r only
    expected = len(re.findall(r"\r\n|\n|\r", text)) + (0 if text.endswith(("\n", "\r")) else 1)
    assert len(split_lines(text)) == expected


def test_whitespace_only_rejected():
    with pytest.raises(ValueError, match="Markdown has no content. The file is blank."):
        pages_of("whitespace_only.md")


def test_bad_encoding():
    path = str(FIXTURES / "latin1.md")
    with pytest.raises(ValueError) as e:
        read_markdown(path)
    assert "latin1.md" in str(e.value) and "UTF-8" in str(e.value)


def test_pager_performance():
    text = ("## Heading\n\n" + "a line of prose for the pager to pack\n" * 40 + "\n") * 700
    assert len(text) > 1_000_000
    with patch("pageindex.markdown_pages.count_tokens", lambda t, model=None: len(t) // 4):
        start = time.perf_counter()
        pages = split_markdown_pages(text)
        elapsed = time.perf_counter() - start
    assert "".join(p.text for p in pages) == text
    assert elapsed < 1.0, elapsed
