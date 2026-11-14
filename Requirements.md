# Requirements: One Indexing Path for PDF and Markdown

| Field | Value |
| --- | --- |
| Branch | `feature/unified-tree-schema` |
| Fork | `jm2909/PageIndex` (upstream: `VectifyAI/PageIndex`, MIT) |
| Status | Phase 1 implemented (offline tests green; not yet run against a real API model) |
| Last updated | 2026-11-14 |

## 1. Objective

PDF and Markdown documents go through **the same indexing pipeline and the same LLM calls**. The only difference is where the text comes from:

- **PDF:** text extracted from each page (PyPDF2 / PyMuPDF), as today.
- **Markdown:** the Markdown text itself, split into pages.

Everything after text extraction (TOC detection, structure generation, verification, fixing, large-node splitting, summaries, description, storage, chat) is shared code with no Markdown-specific branches. So both formats produce the same tree, can be stored the same way, and can be chatted with the same way.

## 2. Background

### 2.1 Problems in upstream

| # | Problem | Evidence |
| --- | --- | --- |
| P1 | Only PDFs can be submitted to the client, in every mode. Markdown has its own indexer, but its output never reaches the store, so chat and agent tools can't use it. | `pageindex/local_api.py:142` rejects non-`.pdf`; `md_to_tree` is called only from `run_pageindex.py` |
| P2 | Markdown uses a separate, regex-only pipeline (`page_index_md.py`), so its tree differs from the PDF tree: `line_num` instead of `start_index`/`end_index`, and `prefix_summary` (parent's own text) instead of `summary` (whole subtree). | `pageindex/page_index_md.py` vs `pageindex/page_index_classic.py` |
| P3 | Standard-mode indexing sends the same page text to the LLM several times in independent calls that can't share a cached prefix. | `pageindex/page_index_classic.py`; `pageindex/utils.py:332` (`_cache_off`) |

### 2.2 The seam: where the text enters

```text
PDF file ──► get_page_tokens()            ┐
             utils.py:970                 │   page_list = [(text, token_count), ...]
             (or LocalAPI._extract_       ├─► page_index_main(doc, opt, page_list)
              page_texts, local_api.py:241)│     page_index_classic.py:1249
MD file  ──► get_markdown_page_tokens()(NEW)┘       └─► tree_parser → check_toc → meta_processor
                                                      → verify/fix → split large nodes
                                                      → summarize_tree → doc description
```

`page_index_main` already accepts a ready-made `page_list`, and everything downstream reads only that list. The only PDF-specific code after the seam is:

- the `.pdf` / `BytesIO` input check (`page_index_classic.py:1259-1265`)
- `get_pdf_name(doc)` for `doc_name` (`page_index_classic.py:1291`, `:1298`)

## 3. Scope

**In scope (this branch):** Phase 1.
**Planned, separate branch:** Phase 2 (indexing cost).
**Out of scope:**

- Flash mode for Markdown. Flash detects structure from PDF layout (font sizes, positions), which Markdown doesn't have.
- The cloud API (`cloud_api.py`, Vectify's hosted service).
- Formats other than `.md` / `.markdown`.

## 4. Functional requirements

### Phase 1: Markdown through the standard pipeline

**FR-1 Markdown helpers mirror the PDF helpers.** Add Markdown counterparts next to the existing PDF text helpers in `pageindex/utils.py`, with the same names (with `pdf` swapped for `markdown`), signatures and return types, so either format can be used anywhere:

| Existing PDF helper (`utils.py`) | New Markdown helper | Returns |
| --- | --- | --- |
| `extract_text_from_pdf(pdf_path)` (line 804) | `extract_text_from_markdown(md_path)` | whole document as one string |
| `get_pdf_title(pdf_path)` (line 813) | `get_markdown_title(md_path)` | first level-1 heading, else `'Untitled'` |
| `get_text_of_pages(pdf_path, start, end, tag=True)` (line 819) | `get_text_of_markdown_pages(md_path, start, end, tag=True)` | text of pages `start..end`, same `<start_index_N>` / `<end_index_N>` tags |
| `get_number_of_pages(pdf_path)` (line 1014) | `get_number_of_markdown_pages(md_path)` | page count (FR-2) |
| `get_page_tokens(pdf_path, model, pdf_parser)` (line 970) | `get_markdown_page_tokens(md_path, model)` | `[(page_text, token_count), ...]` |
| `get_pdf_name(pdf_path)` (line 854) | `get_markdown_name(md_path)` | file name |

Each Markdown helper builds on `get_markdown_page_tokens`, just as the PDF ones build on PyPDF2's page list, so "page N" means the same pages everywhere.

Note: `extract_text_from_pdf`, `get_pdf_title`, `get_text_of_pages` and `get_number_of_pages` are currently unused upstream. They set the pattern, but they aren't on the indexing path. The function that actually feeds the LLM is `get_page_tokens`, called at `page_index_classic.py:1269`.

**FR-1a Dispatch at the real entry point.** `get_page_tokens` sends `.md` / `.markdown` paths to `get_markdown_page_tokens` and keeps its PDF behaviour (PyPDF2 / PyMuPDF) unchanged. Anything else raises a clear `ValueError`. `LocalAPI._extract_page_texts` (`local_api.py:241`) dispatches the same way. These two are the only places that know about file types.

**FR-2 Markdown pages: token-based breaks, formatting kept exactly.** `get_markdown_page_tokens()` reads the file as UTF-8 and cuts it into ordered pages. A page is a **slice of the original file, never a converted or cleaned-up copy**.

*Formatting is preserved:*

- No conversion: no Markdown to plain text or HTML, and no stripping of `#`, `*`, `|`, `>`, links, images, HTML tags or front matter.
- No normalisation: whitespace, indentation, blank lines, trailing spaces (Markdown line breaks), tabs and line endings stay as they are. No `.strip()` on pages.
- Lossless: joining all pages in order (`"".join(pages)`) gives back the original file exactly, byte for byte. Each page keeps its own trailing newline. This matches how `get_text_of_pdf_pages` (`utils.py:998`) joins pages with no separator.

*Where pages break:*

- Size: aim for a token budget per page (`md_page_tokens`, default 800, configurable in `config.yaml`), so existing settings (`toc_check_page_num`, `max_page_num_each_node`, `max_token_num_each_node`, the 20k-token grouping) behave as they do for PDFs.
- Breaks only between whole lines.
- Never inside a block whose meaning depends on staying together:
  - fenced code blocks (```` ``` ```` and `~~~`)
  - tables (consecutive `|` rows, including the header separator row)
  - lists, including nested items and their indented follow-on lines
  - blockquotes (`>` runs)
  - HTML blocks
  - YAML / TOML front matter at the top of the file
- Preferred break points, in order: just before a heading line, then at a blank line between paragraphs.
- A single block bigger than the budget becomes its own oversized page instead of being cut. The only exception is a block larger than `max_token_num_each_node`, which is cut between lines as a last resort and logged as a warning.

*Other rules:*

- Keep each page's `line_start` / `line_end` (1-based, inclusive) next to the list, for storage and citations (FR-6, FR-8).
- Blank-only runs are never dropped, because that would break the lossless rule. They stay attached to the neighbouring page. A file with no non-whitespace content is rejected the same way a blank PDF is ("has no content").
- What the LLM sees: page text goes through the same `_secure_doc_text` step as PDF text (`page_index_classic.py:49`), which replaces a few prompt-injection phrases with `[REDACTED]` and wraps the text in `<user_document>` tags. That applies only to the prompt copy. The pages stored for chat (FR-6) stay exactly as they are in the file.

**FR-3 `page_index_main` accepts Markdown.**

- The input check accepts `.md` / `.markdown` paths in addition to PDFs.
- `doc_name` comes from `get_pdf_name` or `get_markdown_name` (FR-1), chosen by file extension.
- No other change to `tree_parser`, `meta_processor`, `verify_toc`, `fix_incorrect_toc`, `process_large_node_recursively` or `summarize_tree`.

**FR-4 Same LLM calls.** For Markdown, the pipeline makes the same kinds of calls with the same prompts as for a PDF. No Markdown-specific prompts or `if markdown:` branches after the loader. A test checks this by running both formats with the LLM mocked and comparing the sequence of prompt templates used.

**FR-5 Same output.** Markdown output uses the PDF tree format exactly:

```jsonc
{
  "doc_name": "notes.md",
  "source_type": "markdown",     // NEW, "pdf" for PDFs
  "doc_description": "...",      // when if_add_doc_description = yes
  "structure": [
    {
      "title": "Introduction",
      "node_id": "0001",
      "start_index": 1,          // page numbers (Markdown pages from FR-2)
      "end_index": 3,
      "line_start": 1,           // NEW, Markdown only, optional
      "line_end": 118,           // NEW, Markdown only, optional
      "summary": "...",          // covers the whole subtree, as for PDF
      "nodes": [ ... ]
    }
  ]
}
```

`line_start` / `line_end` are worked out from the node's page range after the tree is built. No consumer may require them.

**FR-6 Client accepts Markdown.** `PageIndexClient.submit_document()` in local mode:

- accepts `.md` / `.markdown`
- with `mode=None` uses the standard pipeline for Markdown (Flash stays the default for PDF)
- with `mode="flash"` and a Markdown file, raises a clear error: "Flash mode supports PDF only; Markdown uses standard mode"
- stores the **same** pages the LLM indexed in `pages.json`, as `{"page_index": n, "markdown": text, "line_start": a, "line_end": b}`, so chat reads exactly the text the tree was built from
- sets `meta.source_type = "markdown"` and `meta.pageNum` = number of Markdown pages.

**FR-7 Chat and tools work unchanged.** `get_document`, `get_document_structure`, `get_page_content`, `get_tree`, `get_ocr` (`page` / `node` / `raw`) and local chat return correct results for a Markdown document, with no Markdown-specific code in `agent_tools.py`.

**FR-8 Citations.** For Markdown, citations show the page and, where available, the line range, e.g. `[notes.md, p. 3, lines 120–164]`.

**FR-9 CLI.** `run_pageindex.py --md_path` uses the standard pipeline by default and accepts the same standard-mode options as `--pdf_path` (`--toc-check-pages`, `--max-pages-per-node`, `--max-tokens-per-node`, `--if-add-*`). The old regex indexer (`md_to_tree`) stays available behind `--md-indexer headings`, for indexing without an LLM.

### Phase 2: Indexing cost (separate branch, later)

**FR-10 Cache-friendly prompt order.** Prompts that work on a chunk put the chunk first as a stable, cacheable prefix, with step-specific instructions after it, so later steps over the same chunk can reuse the provider's prompt cache.

**FR-11 Measure first.** Re-enable caching for a model only where it lowers measured cost (input + cache write + cache read) on a benchmark set; otherwise keep today's `_cache_off` behaviour.

**FR-12 Optional summaries during extraction.** Optionally let the structure-generation call also return a short summary per section, removing a separate pass over the same text.

**FR-13 No single growing session.** Don't implement indexing as one long chat session: it breaks on documents larger than the context window, every turn costs more than the last, and summary calls can no longer run in parallel.

## 5. Non-functional requirements

| ID | Requirement |
| --- | --- |
| NFR-1 | **PDF unchanged.** PDF output, prompts and LLM calls stay exactly as today, except for the added `source_type` field. Stored documents without `source_type` load as `pdf`. |
| NFR-2 | **Model requirements.** Markdown indexing needs an API model, as standard mode does today. `claude-code/` models (Flash only) are rejected for Markdown with the existing error message. |
| NFR-3 | **Tests.** Each FR has at least one test, with LLM calls mocked. Includes: page splitting rules (FR-2), including a lossless round trip (`"".join(pages) == file`) and no break inside code blocks, tables, lists, blockquotes, HTML or front matter, using a fixture that contains all of them, same prompt sequence for PDF and Markdown (FR-4), output validated against one JSON Schema for both formats (FR-5), and a local submit → structure → page content → chat round trip for Markdown (FR-6, FR-7). |
| NFR-4 | **Upstream-friendly.** Small, isolated changes that rebase cleanly on `upstream/main`. |
| NFR-5 | **Licence.** Keep the upstream `LICENSE` and copyright notice; don't use the "PageIndex" name for a separately published package. |

## 6. Acceptance criteria

Status as of 2026-11-14; all checks run offline with the LLM mocked (`tests/fake_llm.py`).

- [x] Joining the stored Markdown pages for any test file gives back the original file byte for byte, and no page boundary falls inside a code block, table, list, blockquote, HTML block or front matter. (`tests/test_markdown_pages.py`, `test_markdown_client.py::test_stored_pages_exact`)
- [x] `python run_pageindex.py --md_path doc.md` produces a tree with `start_index`/`end_index`, subtree `summary`, and `source_type: "markdown"`. (`test_markdown_pipeline.py::test_cli_md_standard`, mocked LLM; a real-model run is still to do)
- [x] With the LLM mocked, a PDF and a Markdown document of similar content go through the same sequence of prompt templates. (page-matched: `test_same_prompt_sequence_pdf_vs_md`)
- [x] `client.submit_document("doc.md")` succeeds locally; `get_document_structure` and `get_page_content` on it return the right sections and text. (`test_markdown_client.py::test_tools_work`)
- [x] A local chat question about the Markdown document is answered with a citation pointing to the right page and lines. (`test_markdown_client.py::test_markdown_chat_round_trip`)
- [x] One JSON Schema validates PDF and Markdown output. (`tests/test_tree_schema.py`: PDF standard, PDF Flash, Markdown)
- [x] All existing tests pass; PDF results are unchanged apart from `source_type`. (`test_pdf_unchanged` against the pre-change baseline. Two upstream tests in `test_page_index_md.py` now pass `--md-indexer headings`, because the old indexer is opt-in per FR-9.)

## 7. Open questions

1. ~~**Page size:**~~ Resolved: 800 tokens by default, configurable (`md_page_tokens`, `--md-page-tokens`). Tuning against real PDF page sizes is still open.
2. ~~**Using the headings for free:**~~ Resolved: opt-in heading hint (`md_heading_hint`, `--md-heading-hint`), off by default; allowed by constitution v1.1.0 (Principle III, named exception 1).
3. ~~**Old regex indexer:**~~ Resolved: kept behind `--md-indexer headings`, output format unchanged.
4. **Phase 2 benchmark:** which models and providers?
