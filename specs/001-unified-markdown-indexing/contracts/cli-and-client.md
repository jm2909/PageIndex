# Contract: CLI and local client

## CLI (`run_pageindex.py`)

| Invocation | Behaviour |
| --- | --- |
| `--md_path doc.md` | Standard (LLM) pipeline; writes `results/doc_structure.json` with `source_type: "markdown"` |
| `--md_path doc.md --md-indexer headings` | Old regex indexer (`md_to_tree`), output format unchanged |
| `--md_path doc.md --md-heading-hint` | Standard pipeline with heading hint (FR-017) |
| `--md_path doc.md --toc-check-pages / --max-pages-per-node / --max-tokens-per-node / --if-add-*` | Accepted, same meaning as for PDF standard mode |
| `--md_path doc.md --md-page-tokens N` | Overrides `md_page_tokens` |
| `--md_path doc.md --mode flash` | Error: `Flash mode supports PDF only; Markdown uses standard mode` |
| `--md_path doc.md --if-thinning/--thinning-threshold/--summary-token-threshold` | Only with `--md-indexer headings`; error otherwise |
| `--pdf_path ...` | Unchanged |

## Local client (`PageIndexClient`, local mode)

```python
client.submit_document("notes.md")                 # mode=None → standard
client.submit_document("notes.md", mode="standard")
client.submit_document("notes.md", mode="flash")   # PageIndexAPIError: Flash mode supports PDF only; Markdown uses standard mode
client.submit_document("notes.txt")                # PageIndexAPIError: only PDF and Markdown (.md, .markdown) files are supported in local mode.
client.submit_document("blank.md")                 # PageIndexAPIError: ... Markdown has no content. The file is blank.
```

- Returns `{"doc_id", "name", "usage"}` as for PDF.
- `get_document(doc_id)` meta includes `source_type`.
- `get_ocr(doc_id, format="page")` → `[{"page_index", "markdown", "line_start", "line_end"}]`,
  `markdown` is the exact page slice.
- `get_ocr(doc_id, format="raw")` → the original file text exactly (pages joined with `""`
  for Markdown; PDF keeps its `"\n\n"` join).
- `get_citations(answer, doc_id)` entries for Markdown docs include `line_start`, `line_end`.
- `resolve_citations(...)` renders Markdown citations as `[notes.md, p. 3, lines 120–164]`, in
  each such citation's `label` field (the answer text keeps its numbered links, as for PDF;
  citations without a line range get no `label`, so PDF output is unchanged).
- A heading stays on the same page as the first line after it, so no page ends with a lone
  heading.
- Config: `md_page_tokens` (default 800) and `md_heading_hint` (default `"no"`) in
  `pageindex/config.yaml`; `claude-code/` models raise the existing "flash mode only" error.
