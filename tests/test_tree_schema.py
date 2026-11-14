"""One JSON Schema validates PDF standard, PDF Flash and Markdown trees (FR-008, SC-003)."""
import json
from pathlib import Path

import jsonschema
import pytest

from fake_llm import FakeLLM
from pageindex.page_index_classic import page_index_main
from pageindex.utils import ConfigLoader

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "pageindex" / "schema" / "tree-output.schema.json").read_text())
FLASH_PDFS = sorted((ROOT / "tests" / "data" / "flash").glob("*.pdf"))


@pytest.fixture(autouse=True)
def _in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def test_schema_is_valid():
    jsonschema.Draft202012Validator.check_schema(SCHEMA)


def test_packaged_schema_matches_contract():
    contract = ROOT / "specs" / "001-unified-markdown-indexing" / "contracts" / "tree-output.schema.json"
    if contract.exists():
        assert json.loads(contract.read_text()) == SCHEMA


def test_pdf_standard_validates():
    from conftest import build_pdf
    pdf = Path("doc.pdf")
    pdf.write_bytes(build_pdf([[(72, 700, 12, "# Part One"), (72, 680, 12, "alpha text")],
                               [(72, 700, 12, "# Part Two"), (72, 680, 12, "beta text")]]))
    with FakeLLM().patched():
        result = page_index_main(str(pdf), ConfigLoader().load({"model": "gpt-4o"}))
    jsonschema.validate(result, SCHEMA)
    assert result["source_type"] == "pdf"


@pytest.mark.parametrize("pdf", FLASH_PDFS, ids=lambda p: p.name)
def test_pdf_flash_validates(pdf):
    from pageindex.flash import page_index_flash
    result = page_index_flash(str(pdf), summary=False, optimize=False)  # no LLM at all
    jsonschema.validate(result, SCHEMA)
    assert result["source_type"] == "pdf"


def test_markdown_validates():
    with FakeLLM().patched():
        result = page_index_main(str(ROOT / "tests" / "fixtures" / "markdown" / "all_blocks.md"),
                                 ConfigLoader().load({"model": "gpt-4o"}))
    jsonschema.validate(result, SCHEMA)
    assert result["source_type"] == "markdown"


def test_schema_rejects_missing_source_type():
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"doc_name": "x.pdf", "structure": []}, SCHEMA)
