# Quickstart: validating Unified Markdown Indexing

## Prerequisites

```bash
cd PageIndex
source .venv/bin/activate
pip install -r requirements.txt pytest jsonschema
```

## 1. Offline checks (no API key)

```bash
pytest tests/test_markdown_pages.py tests/test_markdown_helpers.py -q   # lossless + block rules
pytest tests/test_markdown_pipeline.py tests/test_tree_schema.py -q     # same path, shared schema
pytest tests/test_markdown_client.py -q                                 # submit → chat → citations
pytest -q                                                               # full suite incl. upstream
```

Expected: all pass. Coverage of each requirement: [research.md R7](research.md).

## 2. Real run (needs an API model, e.g. `OPENAI_API_KEY`)

```bash
python run_pageindex.py --md_path tests/fixtures/markdown/all_blocks.md
```

Expected: `results/all_blocks_structure.json` validates against
[contracts/tree-output.schema.json](contracts/tree-output.schema.json), has `source_type:
"markdown"`, page ranges and `line_start`/`line_end` on nodes.

```bash
python run_pageindex.py --md_path tests/fixtures/markdown/all_blocks.md --md-heading-hint
python run_pageindex.py --md_path tests/fixtures/markdown/all_blocks.md --md-indexer headings
```

Expected: the hint run reports fewer LLM calls in its usage; the headings run produces the old
format (`line_num`, `prefix_summary`) with no API key needed.

## 3. Client and chat

```python
from pageindex import PageIndexClient
c = PageIndexClient(storage_path="./.pi-store")
doc = c.submit_document("tests/fixtures/markdown/all_blocks.md")
pages = c.get_ocr(doc["doc_id"], format="page")["result"]
assert "".join(p["markdown"] for p in pages) == open(
    "tests/fixtures/markdown/all_blocks.md", encoding="utf-8", newline="").read()
```

Then ask a chat question with citations on and check `get_citations` returns `line_start` and
`line_end`. Behaviour contract: [contracts/cli-and-client.md](contracts/cli-and-client.md).

## 4. PDF regression (real run, needs an API model)

The offline regression check is `test_pdf_unchanged` in section 1; this run is an optional
end-to-end confirmation.

```bash
python run_pageindex.py --pdf_path examples/documents/2023-annual-report-truncated.pdf --mode standard
```

Expected: identical to the upstream result apart from the added `source_type: "pdf"`.
