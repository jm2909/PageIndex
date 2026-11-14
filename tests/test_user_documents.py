"""Optional checks on the owner's own documents (T056).

Set PAGEINDEX_USER_TEST_DIR to a folder of .md / .markdown / .pdf files to run
them; otherwise every test here is skipped. The documents are read in place and
never copied into the repo (Constitution VI). These tests are extra: no
requirement depends on them for its required coverage (Constitution IV).
"""
import json
import os
from pathlib import Path

import jsonschema
import pytest

from fake_llm import FakeLLM
from pageindex.markdown_pages import (page_line_ranges, read_markdown, scan_markdown,
                                      split_lines, split_markdown_pages)
from pageindex.page_index_classic import page_index_main
from pageindex.utils import ConfigLoader

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "pageindex" / "schema" / "tree-output.schema.json").read_text())
USER_DIR = os.environ.get("PAGEINDEX_USER_TEST_DIR")


def _files(*suffixes):
    if not USER_DIR or not Path(USER_DIR).is_dir():
        return []
    root = Path(USER_DIR).resolve()  # the tests chdir into a temp folder
    return sorted(p for p in root.rglob("*") if p.suffix.lower() in suffixes)


def _text_or_skip(path):
    try:
        text = read_markdown(str(path))
    except ValueError as e:
        pytest.skip(f"not UTF-8: {e}")
    if not text.strip():
        pytest.skip("blank file")
    return text


MD_FILES = _files(".md", ".markdown")
PDF_FILES = _files(".pdf")

pytestmark = pytest.mark.skipif(
    not USER_DIR or not Path(USER_DIR).is_dir(),
    reason="set PAGEINDEX_USER_TEST_DIR to a folder of your own test documents")


@pytest.fixture(autouse=True)
def _in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def _ids(p):
    return p.name


@pytest.mark.parametrize("path", MD_FILES, ids=_ids)
def test_user_markdown_pages(path):
    text = _text_or_skip(path)
    pages = split_markdown_pages(text)
    assert "".join(p.text for p in pages) == text
    assert page_line_ranges([(p.text, p.tokens) for p in pages]) == \
        [(p.line_start, p.line_end) for p in pages]
    scan = scan_markdown(split_lines(text))
    for brk in [p.line_start - 1 for p in pages[1:]]:
        for kind, first, last in scan.blocks:
            if first < brk <= last:
                # allowed only for a logged oversized cut
                assert kind in ("fence", "list", "table", "blockquote", "html"), (kind, brk)


@pytest.mark.parametrize("path", MD_FILES, ids=_ids)
def test_user_markdown_tree(path):
    _text_or_skip(path)
    with FakeLLM().patched():
        result = page_index_main(str(path), ConfigLoader().load({"model": "gpt-4o"}))
    jsonschema.validate(result, SCHEMA)
    assert result["source_type"] == "markdown"


@pytest.mark.parametrize("path", PDF_FILES, ids=_ids)
def test_user_pdf_standard_tree(path):
    with FakeLLM().patched():
        result = page_index_main(str(path), ConfigLoader().load({"model": "gpt-4o"}))
    jsonschema.validate(result, SCHEMA)
    assert result["source_type"] == "pdf"


@pytest.mark.parametrize("path", PDF_FILES, ids=_ids)
def test_user_pdf_flash_tree(path):
    from pageindex.flash import page_index_flash
    result = page_index_flash(str(path), summary=False, optimize=False)
    jsonschema.validate(result, SCHEMA)
    assert result["source_type"] == "pdf"
