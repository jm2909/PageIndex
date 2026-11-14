"""User Story 3: submit, browse and cite a Markdown document in the local client;
User Story 4: documents stored before this change still behave as PDFs."""
import json
from pathlib import Path

import pytest

from fake_llm import FakeLLM
from pageindex import PageIndexAPIError, PageIndexLocalClient
from pageindex.agent_tools import call_tool
from pageindex.local_store import DocStore
from pageindex.markdown_pages import read_markdown

FIXTURES = Path(__file__).parent / "fixtures" / "markdown"
ALL_BLOCKS = FIXTURES / "all_blocks.md"


@pytest.fixture(autouse=True)
def _in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def client(tmp_path):
    return PageIndexLocalClient(storage_path=str(tmp_path / "store"))


@pytest.fixture
def md_doc(client):
    with FakeLLM().patched():
        return client.submit_document(str(ALL_BLOCKS))


# ------------------------------------------------------------ submit (T038) ---

def test_submit_md(md_doc):
    assert md_doc["doc_id"].startswith("pi-") and md_doc["name"] == "all_blocks.md"


def test_default_mode_standard(client, md_doc):
    meta = client._api._store.get_meta(md_doc["doc_id"])
    assert meta["mode"] == "standard"
    assert meta["source_type"] == "markdown"
    pages = client.get_ocr(md_doc["doc_id"], format="page")["result"]
    assert meta["pageNum"] == len(pages)
    assert client.get_document(md_doc["doc_id"])["source_type"] == "markdown"


# -------------------------------------------------------- rejections (T039) ---

def test_flash_rejected(client):
    with pytest.raises(PageIndexAPIError, match="Flash mode supports PDF only; Markdown uses standard mode"):
        client.submit_document(str(ALL_BLOCKS), mode="flash")


def test_unsupported_type_rejected(client, tmp_path):
    txt = tmp_path / "notes.txt"
    txt.write_text("hello", encoding="utf-8")
    with pytest.raises(PageIndexAPIError,
                       match=r"only PDF and Markdown \(\.md, \.markdown\) files are supported in local mode\."):
        client.submit_document(str(txt))


def test_blank_md_rejected(client):
    with pytest.raises(PageIndexAPIError,
                       match="Failed to submit document: Markdown has no content. The file is blank."):
        client.submit_document(str(FIXTURES / "whitespace_only.md"))


def test_bad_encoding_rejected(client):
    with pytest.raises(PageIndexAPIError, match=r"latin1\.md.*UTF-8"):
        client.submit_document(str(FIXTURES / "latin1.md"))


def test_headings_indexer_output_not_accepted(client, tmp_path):
    """FR-016: the old indexer's JSON is not a document the client accepts."""
    out = tmp_path / "notes_structure.json"
    out.write_text(json.dumps({"doc_name": "notes", "structure": [{"title": "t", "line_num": 1}]}))
    with pytest.raises(PageIndexAPIError, match="only PDF and Markdown"):
        client.submit_document(str(out))


# ------------------------------------------------------- stored pages (T040) ---

def test_stored_pages_exact(client, md_doc):
    text = read_markdown(str(ALL_BLOCKS))
    pages = client.get_ocr(md_doc["doc_id"], format="page")["result"]
    assert all({"page_index", "markdown", "line_start", "line_end"} <= set(p) for p in pages)
    assert "".join(p["markdown"] for p in pages) == text
    assert pages[0]["line_start"] == 1
    assert client.get_ocr(md_doc["doc_id"], format="raw")["result"] == text


# --------------------------------------------------------------- tools (T041) ---

def tool(client, name, **arguments):
    text, is_error = call_tool(client, name, arguments)
    assert not is_error, text
    return json.loads(text)


def test_tools_work(client, md_doc):
    doc = tool(client, "get_document", doc_name="all_blocks.md")
    assert doc["name"] == "all_blocks.md" if "name" in doc else True

    structure = json.dumps(tool(client, "get_document_structure", doc_name="all_blocks.md"))
    titles = [n["title"] for n in _walk(client.get_tree(md_doc["doc_id"])["result"])]
    assert titles and all(json.dumps(t) in structure for t in titles)

    pages = client.get_ocr(md_doc["doc_id"], format="page")["result"]
    content = json.dumps(tool(client, "get_page_content", doc_name="all_blocks.md", pages="2"))
    first_line = pages[1]["markdown"].splitlines()[0]
    assert json.dumps(first_line)[1:-1] in content  # the exact text, JSON-escaped

    tree = client.get_tree(md_doc["doc_id"])["result"]
    nodes = list(_walk(tree))
    assert nodes and all("line_start" in n and "line_end" in n for n in nodes)


def _walk(nodes):
    for n in nodes:
        yield n
        yield from _walk(n.get("nodes") or [])


# ----------------------------------------------------------- citations (T042) ---

def test_citation_line_ranges(client, md_doc):
    pages = client.get_ocr(md_doc["doc_id"], format="page")["result"]
    a, b = pages[1]["line_start"], pages[1]["line_end"]
    answer = 'Fences keep tabs.<cite doc="all_blocks.md" page="2"/>'
    cites = client.get_citations(answer, doc_id=md_doc["doc_id"])
    assert cites[0]["line_start"] == a and cites[0]["line_end"] == b
    resolved = client.resolve_citations(answer, doc_id=md_doc["doc_id"])
    assert resolved["citations"][0]["label"] == f"[all_blocks.md, p. 2, lines {a}–{b}]"


def test_pdf_citations_unchanged(client, tmp_path):
    seed_old_pdf(tmp_path / "store", "pi-old", "report.pdf")
    answer = '<cite doc="report.pdf" page="1"/>'
    cites = client.get_citations(answer, doc_id="pi-old")
    assert cites == [{"document": "report.pdf", "doc_id": "pi-old", "page": 1}]
    assert "label" not in client.resolve_citations(answer, doc_id="pi-old")["citations"][0]


# ------------------------------------- chat round trip (Constitution IV) ---

from test_local_chat import _call_item, _msg_item, fake_model, needs_agents  # noqa: E402,F401


@needs_agents
def test_markdown_chat_round_trip(client, md_doc, fake_model):
    """submit → structure → page content → chat answer with a line-range citation,
    the tools running for real against the stored Markdown document."""
    pages = client.get_ocr(md_doc["doc_id"], format="page")["result"]
    answer = 'The fixture keeps fenced code intact.<cite doc="all_blocks.md" page="2"/>'
    fake = fake_model([
        [_call_item("get_document_structure", {"doc_name": "all_blocks.md"}, call_id="c1")],
        [_call_item("get_page_content", {"doc_name": "all_blocks.md", "pages": "2"}, call_id="c2")],
        [_msg_item(answer)],
    ])
    out = client.chat("How are code fences handled?", doc_id=md_doc["doc_id"])
    assert out == answer
    turn3 = json.dumps(fake.inputs[2])
    assert json.dumps(pages[1]["markdown"].splitlines()[0])[1:-1] in turn3  # exact page text
    cite = client.get_citations(out, doc_id=md_doc["doc_id"])[0]
    assert (cite["page"], cite["line_start"], cite["line_end"]) == \
        (2, pages[1]["line_start"], pages[1]["line_end"])


# ------------------------------------------------------- claude-code (T043) ---

def test_claude_code_rejected_for_md(tmp_path):
    client = PageIndexLocalClient(storage_path=str(tmp_path / "s"), index_model="claude-code/haiku")
    with pytest.raises(PageIndexAPIError, match="flash mode only"):
        client.submit_document(str(ALL_BLOCKS))


# ------------------------------------------------- old documents (T036) ---

def seed_old_pdf(store_path, doc_id, name):
    """A document as stored before this change: no source_type anywhere."""
    pages = [{"page_index": 1, "markdown": "Page one"}, {"page_index": 2, "markdown": "Page two"}]
    tree = [{"title": "Doc", "node_id": "0000", "start_index": 1, "end_index": 2, "summary": "s"}]
    meta = {"id": doc_id, "name": name, "description": "d", "status": "completed",
            "createdAt": "2026-01-01T00:00:00", "pageNum": 2, "folderId": None,
            "metadata": None, "mode": "standard"}
    DocStore(str(store_path)).save_document(doc_id, meta, tree, pages)


def test_old_documents_default_pdf(client, tmp_path):
    seed_old_pdf(tmp_path / "store", "pi-old", "report.pdf")
    assert client.get_document("pi-old")["source_type"] == "pdf"
    assert client.get_ocr("pi-old", format="raw")["result"] == "Page one\n\nPage two"
    tree = client.get_tree("pi-old")["result"]
    assert tree[0]["title"] == "Doc" and "line_start" not in tree[0]
