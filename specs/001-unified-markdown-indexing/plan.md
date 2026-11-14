# Implementation Plan: Unified Markdown Indexing

**Branch**: `feature/unified-tree-schema` | **Date**: 2026-11-14 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-unified-markdown-indexing/spec.md`

## Summary

Send Markdown through PageIndex's existing **standard** (LLM) indexing pipeline by swapping only
the text source. The pipeline already takes a ready-made `page_list = [(text, tokens), ...]`
(`page_index_main(doc, opt, page_list=...)`), and every step after it reads only that list. So we
add a lossless, block-aware Markdown pager that produces the same `page_list` shape, plus Markdown
counterparts of the PDF text helpers, and dispatch to it by file extension at the two places text
enters (`utils.get_page_tokens`, `LocalAPI._extract_page_texts`). Output gains `source_type` and,
for Markdown, optional `line_start`/`line_end`. Two clarified extras: an opt-in heading hint that
feeds Markdown headings into the existing "TOC with page numbers" handling, and the old regex
indexer kept unchanged behind a CLI option.

## Technical Context

**Language/Version**: Python ≥ 3.11 per the constitution; `pyproject.toml` is raised from
upstream's `>=3.10` to `>=3.11` (venv: 3.12). See Complexity Tracking.

**Primary Dependencies**: existing only — LiteLLM (LLM calls, `token_counter`), PyPDF2,
pypdfium2, PyYAML. No new runtime dependency. Markdown block detection is hand-written
line scanning (see research R2). `jsonschema` added as a **dev/test-only** dependency for the
shared schema test (research R6).

**Storage**: local file store (`LocalStore`: `tree.json`, `pages.json`, `doc.json` per document)

**Testing**: pytest; LLM calls mocked with `unittest.mock.patch` as in `tests/test_page_index.py`;
`tests/conftest.py` already sets fake API keys

**Target Platform**: macOS / Linux, library + CLI

**Project Type**: Python library with CLI (`run_pageindex.py`) and local client (`PageIndexClient`)

**Performance Goals**: Markdown paging is O(file size) and adds < 1 s for a 1 MB file excluding
token counting; LLM cost for Markdown ≈ PDF standard mode of the same token count

**Constraints**: PDF output/prompts byte-identical (Constitution I); pages lossless (II); no
format branches after the text-entry seam (III); tests offline (IV)

**Scale/Scope**: ~6 touched upstream files, 1 new module, ~8 new test files/fixtures

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status (pre) | Status (post-design) |
| --- | --- | --- | --- |
| I. PDF Behaviour Unchanged | PDF path code untouched except an extension check and the added `source_type` key; regression test compares prompts/output | PASS | PASS — PDF branches in `get_page_tokens`, `_extract_page_texts`, `page_index_main` keep existing code verbatim |
| II. Markdown Formatting Preserved | Pager is lossless and block-aware; stored pages = exact slices | PASS | PASS — see data-model "Page" invariants and contract `markdown-pager.md` |
| III. One Indexing Path | Format code only at text entry (loader, name, input check, Flash guard) plus the constitution's named exceptions (v1.1.0) | PASS | PASS — the only Markdown-only steps after text entry are named exceptions 1–3: heading hint (`process_toc_hint`, T033), line ranges on nodes/pages/citations (T027, T046, T047), raw-view `""` join (T046). No prompt text changes. |
| IV. Tests for Every Requirement | Every FR mapped to a test; mocked LLM | PASS | PASS — FR→test map in research R7 |
| V. Upstream-Friendly | New module + small edits; no refactors | PASS | PASS (one justified deviation) — new code in `pageindex/markdown_pages.py`; helpers appended to `utils.py`; `pyproject.toml` Python minimum raised (Complexity Tracking) |
| VI. Licence & Attribution | LICENSE untouched; no renaming | PASS | PASS |

Citations (FR-012) deliberately do **not** change the citation prompt (that would be a
format-specific prompt, violating III): the LLM still cites `doc` + `page`, and line ranges are
added when citations are resolved, from stored page metadata (research R5).

## Project Structure

### Documentation (this feature)

```text
specs/001-unified-markdown-indexing/
├── plan.md              # This file
├── research.md          # Phase 0 decisions
├── data-model.md        # Phase 1 entities and invariants
├── quickstart.md        # Phase 1 validation guide
├── contracts/
│   ├── markdown-pager.md        # pager + helper function contracts
│   ├── tree-output.schema.json  # shared JSON Schema for PDF + Markdown trees
│   └── cli-and-client.md        # CLI flags and client behaviour
├── checklists/requirements.md
└── tasks.md             # /speckit-tasks output
```

### Source Code (repository root)

```text
pageindex/
├── markdown_pages.py        # NEW: block-aware lossless pager (MarkdownPage, split_markdown_pages,
│                            #      heading extraction for the hint)
├── utils.py                 # + Markdown helper counterparts (extract_text_from_markdown, ...);
│                            #   get_page_tokens dispatches .md/.markdown; get_doc_name helper
├── page_index_classic.py    # input check accepts Markdown; doc_name by extension; source_type;
│                            #   line ranges on nodes; meta_processor 'process_toc_hint' mode
├── local_api.py             # accept .md; Flash guard; store pages with line ranges; source_type
├── client.py                # get_citations/resolve_citations add line ranges for Markdown docs
├── schema/
│   └── tree-output.schema.json  # NEW: copy of the contract schema, shipped as package data
└── config.yaml              # + md_page_tokens: 800, md_heading_hint: "no"

run_pageindex.py             # --md_path → standard pipeline; --md-indexer {llm,headings};
                             #   --md-heading-hint; standard-mode flags allowed for Markdown

tests/
├── fixtures/markdown/       # NEW: all_blocks.md, no_headings.md, crlf.md, unclosed_fence.md,
│                            #      whitespace_only.md, big_code_block.md, huge_block.md,
│                            #      injection.md, latin1.md
├── tools/capture_pdf_baseline.py  # NEW: records the PDF baseline (T002)
├── data/pdf_baseline/       # NEW: prompt templates + output hashes only (no document text)
├── test_markdown_pages.py   # NEW: lossless, no-break-inside-block, line ranges, budgets
├── test_markdown_helpers.py # NEW: helper counterparts mirror PDF helpers
├── test_markdown_pipeline.py# NEW: same prompt sequence PDF vs MD; heading hint; redaction
├── test_tree_schema.py      # NEW: PDF std, PDF flash, MD all validate against shared schema
├── test_markdown_client.py  # NEW: submit → structure → page content → chat → citations
└── test_page_index_md.py    # existing; still passes (old indexer unchanged)
```

**Structure Decision**: single Python package (`pageindex/`) plus top-level CLI and `tests/`, as
upstream. All new logic sits in one new module so rebasing on upstream touches few lines.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
| --- | --- | --- |
| Principle V: `pyproject.toml` Python minimum raised from `>=3.10` to `>=3.11` | Constitution's Technical Constraints require ≥ 3.11 (owner's decision, 2026-11-14) | Lowering the constitution to 3.10 was offered and declined; this is a one-line change, easy to rebase |
| Principle III exception 1 (now named in constitution v1.1.0): Markdown-only `process_toc_hint` mode in `meta_processor` (FR-017) | User chose an opt-in heading hint in clarification to cut LLM calls on well-structured Markdown | Feeding headings through the existing `process_toc_with_page_numbers` needs a TOC *page* and printed page numbers, which Markdown lacks; faking a TOC page would alter the LLM's input and prompts. The new mode reuses `verify_toc` / `fix_incorrect_toc_with_retries` and falls back to `process_no_toc`, so behaviour is still verified by the same LLM steps. Off by default, so the default path stays identical to PDF. |
| Principle III: Flash-mode guard for Markdown (FR-013) | Flash reads PDF layout | Allowed explicitly by the constitution ("Flash-mode guard"); listed for completeness |
