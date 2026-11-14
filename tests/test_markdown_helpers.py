"""Markdown counterparts of the PDF text helpers (FR-002) and path helpers."""
from io import BytesIO
from pathlib import Path

import pytest

from pageindex import utils
from pageindex.markdown_pages import read_markdown

FIXTURES = Path(__file__).parent / "fixtures" / "markdown"
ALL_BLOCKS = str(FIXTURES / "all_blocks.md")


# --- T007: path helpers -------------------------------------------------------

@pytest.mark.parametrize("path, expected", [
    ("notes.md", True), ("NOTES.MD", True), ("a/b/c.markdown", True), ("x.Markdown", True),
    ("doc.pdf", False), ("notes.txt", False), ("md", False), ("notes.md.pdf", False),
])
def test_is_markdown_path(path, expected):
    assert utils.is_markdown_path(path) is expected


def test_is_markdown_path_non_str():
    assert utils.is_markdown_path(BytesIO(b"%PDF")) is False
    assert utils.is_markdown_path(None) is False


def test_get_doc_name():
    assert utils.get_doc_name("/tmp/dir/notes.md") == "notes.md"
    assert utils.get_doc_name("/tmp/dir/report.pdf") == "report.pdf"  # get_pdf_name's answer


# --- T018: helper counterparts mirror their PDF twins -------------------------

def test_extract_text_from_markdown():
    assert utils.extract_text_from_markdown(ALL_BLOCKS) == read_markdown(ALL_BLOCKS)


def test_get_markdown_title(tmp_path):
    assert utils.get_markdown_title(ALL_BLOCKS) == "All Blocks Fixture"
    plain = tmp_path / "plain.md"
    plain.write_text("no headings here\n", encoding="utf-8")
    assert utils.get_markdown_title(str(plain)) == "Untitled"


def test_get_markdown_page_tokens_and_pages():
    pages = utils.get_markdown_pages(ALL_BLOCKS)
    page_list = utils.get_markdown_page_tokens(ALL_BLOCKS)
    assert page_list == [(p.text, p.tokens) for p in pages]
    assert "".join(t for t, _ in page_list) == read_markdown(ALL_BLOCKS)


def test_get_markdown_pages_reads_config_and_overrides():
    default = utils.get_markdown_pages(ALL_BLOCKS)
    small = utils.get_markdown_pages(ALL_BLOCKS, page_tokens=100)
    assert len(small) > len(default)


def test_get_number_of_markdown_pages():
    assert utils.get_number_of_markdown_pages(ALL_BLOCKS, ) == len(utils.get_markdown_pages(ALL_BLOCKS))


def test_get_text_of_markdown_pages_tags():
    pages = utils.get_markdown_pages(ALL_BLOCKS, page_tokens=100)
    tagged = utils.get_text_of_markdown_pages(ALL_BLOCKS, 1, 2, page_tokens=100)
    assert tagged == (f"<start_index_1>\n{pages[0].text}\n<end_index_1>\n"
                      f"<start_index_2>\n{pages[1].text}\n<end_index_2>\n")
    plain = utils.get_text_of_markdown_pages(ALL_BLOCKS, 1, 2, tag=False, page_tokens=100)
    assert plain == pages[0].text + pages[1].text


def test_get_markdown_name():
    assert utils.get_markdown_name(ALL_BLOCKS) == "all_blocks.md"


def test_get_page_tokens_dispatches_markdown():
    assert utils.get_page_tokens(ALL_BLOCKS) == utils.get_markdown_page_tokens(ALL_BLOCKS)


def test_unsupported_extension(tmp_path):
    from pageindex.page_index_classic import page_index_main
    txt = tmp_path / "notes.txt"
    txt.write_text("hello", encoding="utf-8")
    with pytest.raises(ValueError, match=r"Expected a PDF or Markdown \(\.md, \.markdown\)"):
        page_index_main(str(txt), utils.ConfigLoader().load())
