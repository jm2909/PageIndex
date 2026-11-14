---

description: "Task list for Unified Markdown Indexing"
---

# Tasks: Unified Markdown Indexing

**Input**: Design documents from `specs/001-unified-markdown-indexing/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: Required. Constitution Principle IV makes tests mandatory for every requirement; they
are written first and must fail before implementation. All LLM calls are mocked.

**Organization**: Tasks are grouped by user story. Story order follows dependencies: US2 (the
pager) comes before US1 (the pipeline), because the pipeline consumes the pager's output.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1–US4 from [spec.md](spec.md)
- Paths are relative to the repository root (`PageIndex/`)

---

## Phase 1: Setup

**Purpose**: Test tooling, config defaults and fixtures

- [X] T001 Install dev dependencies in `.venv` (`pip install -r requirements.txt pytest jsonschema`) and add `jsonschema` under `[tool.poetry.group.dev.dependencies]` in `pyproject.toml`; raise `python` in `pyproject.toml` from `">=3.10"` to `">=3.11"` (constitution Technical Constraints; justified in plan Complexity Tracking)
- [X] T002 Record a PDF baseline before any change: run the existing suite (`pytest -q`) and, via a helper script `tests/tools/capture_pdf_baseline.py`, save for `examples/documents/2023-annual-report-truncated.pdf` (standard mode, mocked LLM) **only** the ordered prompt-template names, a SHA-256 of each full prompt and a SHA-256 of the canonical-JSON output to `tests/data/pdf_baseline/`. No document text is written to the repo (Constitution VI)
- [X] T003 [P] Add config defaults `md_page_tokens: 800` and `md_heading_hint: "no"` to `pageindex/config.yaml` (comment: Markdown only, no effect on PDFs)
- [X] T004 [P] Create Markdown fixtures in `tests/fixtures/markdown/`: `all_blocks.md` (YAML front matter, ATX + setext headings, paragraphs, ``` and ~~~ fences, a table, nested lists, blockquote, HTML block, trailing-space line breaks, tabs), `no_headings.md`, `crlf.md` (CRLF + mixed endings), `unclosed_fence.md`, `whitespace_only.md`, `big_code_block.md` (single fence > 800 tokens), `huge_block.md` (single fence > 20,000 tokens), `injection.md` (contains "ignore previous instructions"), `latin1.md` (invalid UTF-8 bytes)
- [X] T005 [P] Copy `specs/001-unified-markdown-indexing/contracts/tree-output.schema.json` to `pageindex/schema/tree-output.schema.json` and include it as package data in `pyproject.toml`

---

## Phase 2: Foundational

**Purpose**: Shared helpers every story uses

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T006 Add `is_markdown_path(path)` (str path ending `.md` / `.markdown`, case-insensitive) and `get_doc_name(doc)` (Markdown → base file name; otherwise delegates to existing `get_pdf_name`) to `pageindex/utils.py`, placed next to `get_pdf_name`; PDF code untouched
- [X] T007 Add unit tests for `is_markdown_path` and `get_doc_name` in `tests/test_markdown_helpers.py`

**Checkpoint**: Foundation ready

---

## Phase 3: User Story 2 - Markdown formatting reaches the pipeline exactly as written (Priority: P1) 🎯 MVP part 1

**Goal**: A lossless, block-aware Markdown pager

**Independent Test**: Split every fixture; joined pages equal the file byte for byte and no break
falls inside a protected block

### Tests for User Story 2 ⚠️ (write first, must fail)

- [X] T008 [P] [US2] `test_lossless_round_trip` over all fixtures (including `crlf.md`, `unclosed_fence.md`) asserting `"".join(p.text for p in pages) == read_markdown(path)` in `tests/test_markdown_pages.py`
- [X] T009 [P] [US2] `test_no_break_inside_protected_blocks` for front matter, ``` / ~~~ fences, tables, lists, blockquotes, HTML blocks, setext heading pairs, using `all_blocks.md` with a small `page_tokens` (e.g. 50) to force many breaks, in `tests/test_markdown_pages.py`
- [X] T010 [P] [US2] `test_budget_and_preferred_breaks`: pages ≤ budget unless a single block is larger; breaks prefer "before heading" then "blank line", in `tests/test_markdown_pages.py`
- [X] T011 [P] [US2] `test_oversized_block_warning`: `big_code_block.md` stays one page; `huge_block.md` (> `max_block_tokens` 20000) is cut between lines with a logged warning (`caplog`); plus `test_cut_threshold_follows_max_tokens_per_node`: with `max_block_tokens=1000`, `big_code_block.md` is cut with a warning (proves the threshold is a parameter, not hard-coded), in `tests/test_markdown_pages.py`
- [X] T012 [P] [US2] `test_line_ranges` (parametrised over all fixtures, including `crlf.md` with mixed endings): `line_start` of page 1 is 1, ranges are contiguous (`pages[i].line_end + 1 == pages[i+1].line_start`), last `line_end` equals total lines, in `tests/test_markdown_pages.py`
- [X] T013 [P] [US2] `test_whitespace_only_rejected` ("Markdown has no content. The file is blank.") and `test_bad_encoding` (`latin1.md` → ValueError naming the file and UTF-8), in `tests/test_markdown_pages.py`

### Implementation for User Story 2

- [X] T014 [US2] Create `pageindex/markdown_pages.py` with frozen dataclass `MarkdownPage(page_index: int, text: str, tokens: int, line_start: int, line_end: int)` and `read_markdown(md_path)` (UTF-8, `newline=""`, ValueError on decode error) per [contracts/markdown-pager.md](contracts/markdown-pager.md)
- [X] T015 [US2] Implement the line scanner in `pageindex/markdown_pages.py` that marks protected-block membership and safe break points, using the rules in [research.md R2](research.md) (front matter only at line 1; fences close on same char with ≥ length; unclosed fence runs to EOF; tables; lists with indented continuation; blockquotes; HTML blocks to next blank line; setext pairs kept together)
- [X] T016 [US2] Implement `split_markdown_pages(text, model=None, page_tokens=800, max_block_tokens=20000)` in `pageindex/markdown_pages.py`: greedy packing per [research.md R3](research.md), tokens via `pageindex.utils.count_tokens`, `splitlines(keepends=True)`, whitespace runs attached to neighbours, last-resort line cut with `logging.warning`, blank file → ValueError
- [X] T054 [P] [US2] `test_pager_performance`: a generated ~1 MB Markdown file pages in < 1 s with `count_tokens` patched to a cheap stub (plan Performance Goals), in `tests/test_markdown_pages.py`
- [X] T017 [US2] Run `tests/test_markdown_pages.py` until green

**Checkpoint**: The pager is complete and verified on its own

---

## Phase 4: User Story 1 - Index a Markdown file into the same tree as a PDF (Priority: P1) 🎯 MVP part 2

**Goal**: Markdown flows through the standard pipeline via the same `page_list`, producing the
shared tree format

**Independent Test**: Index `all_blocks.md` with the LLM mocked; output validates against the
shared schema and uses the same prompt-template sequence as a PDF

### Tests for User Story 1 ⚠️ (write first, must fail)

- [X] T018 [P] [US1] One test per Markdown helper mirroring its PDF twin (`extract_text_from_markdown`, `get_markdown_title`, `get_text_of_markdown_pages` with `<start_index_N>`/`<end_index_N>` tags, `get_number_of_markdown_pages`, `get_markdown_page_tokens`, `get_markdown_name`) plus `test_unsupported_extension`, in `tests/test_markdown_helpers.py`
- [X] T019 [P] [US1] `test_same_prompt_sequence_pdf_vs_md` (page-matched): split a Markdown fixture with `split_markdown_pages`, then build the PDF with `tests/conftest.py::build_pdf`, passing for each Markdown page a list of `(72, y, 10, line)` tuples (one per line, `y` stepping down the page) so the PDF has exactly one physical page per Markdown page and multi-line text extracts cleanly. Use an ASCII-only fixture (Helvetica/WinAnsi) with no tabs. Patch `llm_completion`/`llm_acompletion` to record, for every call in order, the prompt template it came from (identified by the template's fixed text, not by document content). Index both with the same `opt`, then assert the two recorded lists are **identical, repeats included** (same templates, same order, same counts) and that both runs have equal `len(page_list)`. Keep the fixture well under the 20k-token grouping threshold so small token-count differences from PDF text extraction can't change the grouping. In `tests/test_markdown_pipeline.py`
- [X] T020 [P] [US1] `test_node_line_ranges`: nodes carry `line_start`/`line_end` derived per [data-model.md](data-model.md) "Heading match rule" and "Line range derivation", including a title that differs only in case/emphasis (matches) and a title not on its start page (falls back to page `line_start`); plus `test_page_line_ranges_match_pager` (for every fixture, `page_line_ranges([(p.text, p.tokens) for p in pages])` equals the `MarkdownPage` ranges) and `test_line_ranges_via_page_list_only` (call `page_index_main(md_path, opt, page_list=...)` as the local client does; nodes still get line ranges), in `tests/test_markdown_pipeline.py`
- [X] T021 [P] [US1] `test_redaction_prompt_only` with `injection.md`: the recorded prompt contains `[REDACTED]`; the returned page text does not, in `tests/test_markdown_pipeline.py`
- [X] T022 [P] [US1] CLI tests run **in-process** with `runpy.run_path("run_pageindex.py", run_name="__main__")` under `monkeypatch.setattr(sys, "argv", [...])` and `patch` on `llm_completion`/`llm_acompletion` (no subprocess, no change to the upstream script's structure): `test_cli_md_standard` (`--md_path`, output has `source_type: "markdown"`), `test_cli_md_indexer_headings` (old format: `line_num`, no API key), `test_cli_md_flash_rejected`, `test_cli_thinning_requires_headings_indexer`, and `test_cli_md_overrides_reach_pager` (`--md-page-tokens`, `--max-tokens-per-node`), in `tests/test_markdown_pipeline.py`
- [X] T055 [P] [US1] `test_long_markdown_uses_shared_chunking`: a Markdown file whose total tokens exceed the 20k grouping threshold produces multiple `process_no_toc` groups (same grouping as a long PDF), in `tests/test_markdown_pipeline.py`
- [X] T023 [P] [US1] Shared schema test: PDF standard output, PDF flash output (run Flash offline on the repo's `tests/data/flash/*.pdf` with `tree_optimize.ask_model` patched, as `tests/test_flash_extraction.py` does) and Markdown output all validate against `pageindex/schema/tree-output.schema.json` with `"source_type"` present, in `tests/test_tree_schema.py`

### Implementation for User Story 1

- [X] T024 [US1] Add `get_markdown_pages(md_path, model=None, page_tokens=None, max_block_tokens=None)` (None → `md_page_tokens` / `max_token_num_each_node` from config), `get_markdown_page_tokens` with the same optional arguments, and the Markdown helper counterparts from [contracts/markdown-pager.md](contracts/markdown-pager.md) to `pageindex/utils.py`, each placed right after its PDF twin
- [X] T025 [US1] In `pageindex/utils.py::get_page_tokens`, add a first branch `if is_markdown_path(pdf_path): return get_markdown_page_tokens(pdf_path, model)`; leave the PyPDF2/PyMuPDF code byte-for-byte unchanged
- [X] T026 [US1] In `pageindex/page_index_classic.py::page_index_main`: accept Markdown paths in the input check (error text "Unsupported input type. Expected a PDF or Markdown (.md, .markdown) file path or a PDF BytesIO object."), use `get_doc_name(doc)` for `doc_name`; when `page_list is None` and the input is Markdown, load pages with `get_markdown_page_tokens(doc, opt.model, page_tokens=opt.md_page_tokens, max_block_tokens=opt.max_token_num_each_node)` (text entry); and add `"source_type"` (`"markdown"` or `"pdf"`) to both return dicts
- [X] T027 [US1] Add `page_line_ranges(page_list)` and `add_markdown_line_ranges(structure, page_list)` in `pageindex/markdown_pages.py` per [contracts/markdown-pager.md](contracts/markdown-pager.md) (line ranges derived from the `(text, tokens)` page texts alone, so they work on the local-client path where only `page_list` is passed in), implementing the derivation rule, and call it from `page_index_main` only when the input is Markdown (Constitution III named exception 2, line ranges), before `format_structure`; add `line_start`, `line_end` to the `format_structure` key order after `end_index`
- [X] T057 [US1] Add optional `md_page_tokens=None` and `md_heading_hint=None` parameters to the library wrapper `pageindex/page_index_classic.py::page_index(...)` (appended after the existing ones, so positional callers are unaffected; `None` keeps the config default), and test `test_library_call_md_options` in `tests/test_markdown_pipeline.py`: `page_index("x.md", md_page_tokens=200)` gives more pages than the default, and `md_heading_hint="yes"` takes the hint path (FR-001, FR-017)
- [X] T028 [US1] Add `"source_type": "pdf"` to Flash results in `pageindex/flash/api.py` (envelope only; no other change)
- [X] T029 [US1] Update `run_pageindex.py`: `--md_path` runs `page_index_main` (standard) by default; add `--md-indexer {llm,headings}` (default `llm`; `headings` calls existing `md_to_tree` unchanged), `--md-page-tokens N`; allow `--toc-check-pages`, `--max-pages-per-node`, `--max-tokens-per-node`, `--if-add-*` for Markdown; `--mode flash` with `--md_path` → error "Flash mode supports PDF only; Markdown uses standard mode"; `--if-thinning`/`--thinning-threshold`/`--summary-token-threshold` only with `--md-indexer headings`
- [X] T030 [US1] Run `tests/test_markdown_helpers.py`, `tests/test_markdown_pipeline.py`, `tests/test_tree_schema.py`, `tests/test_page_index_md.py` until green

### Heading hint (FR-017, part of User Story 1)

- [X] T031 [P] [US1] Tests `test_hint_off_identical` (hint off → same template sequence as T019) and `test_heading_hint_fewer_calls` (hint on → fewer recorded LLM calls; output still validates against the schema; low verify accuracy falls back to `process_no_toc`), and `test_hint_ignored_for_pdf`, in `tests/test_markdown_pipeline.py`
- [X] T032 [US1] Implement `extract_heading_toc(page_list)` in `pageindex/markdown_pages.py` per [research.md R4](research.md): takes the pipeline's `(text, tokens)` list, runs the scanner over the pages in order carrying fence/front-matter state across page boundaries (a heading-like line inside a fence that spans two pages is not a heading); ATX + setext headings only; `structure` numbers from levels, skipped levels normalised
- [X] T033 [US1] (Constitution III named exception 1) Add mode `process_toc_hint` to `pageindex/page_index_classic.py::meta_processor` per [research.md R4](research.md): an explicit `elif mode == 'process_toc_hint'` that takes the hint list as `toc_with_page_number`, then the shared validate → `verify_toc` → `fix_incorrect_toc_with_retries` steps, and an explicit fallback branch to `process_no_toc` on accuracy ≤ 0.6. In `tree_parser`, when `opt.md_heading_hint == "yes"`, the document is Markdown and `extract_heading_toc(page_list)` is non-empty, **skip `check_toc`** and call `meta_processor(mode='process_toc_hint')`; otherwise the existing code path runs unchanged
- [X] T034 [US1] Add `--md-heading-hint` flag to `run_pageindex.py` mapping to `md_heading_hint: "yes"`; run T031 tests until green

**Checkpoint**: Markdown produces the shared tree via the shared pipeline

---

## Phase 5: User Story 4 - PDF users see no change (Priority: P1)

**Goal**: Prove PDF behaviour is unchanged

**Independent Test**: Baseline from T002 matches current prompts and outputs; full suite passes

- [X] T035 [P] [US4] `test_pdf_unchanged`: replay the T002 baseline (mocked LLM, same mock responses as T002) and assert (a) the ordered prompt-template names and per-prompt SHA-256 hashes match exactly, (b) the output contains `source_type: "pdf"`, and (c) the SHA-256 of the canonical JSON output **with the `source_type` key removed** matches the baseline output hash, in `tests/test_markdown_pipeline.py`
- [X] T036 [P] [US4] `test_old_documents_default_pdf`: a stored document without `source_type` loads and serves `get_tree`/`get_ocr` as before and reports `pdf`, in `tests/test_markdown_client.py`
- [X] T037 [US4] Run the full suite `pytest -q`; fix any regression in the touched files only
- [X] T056 [P] Owner's document tests in `tests/test_user_documents.py`: read the folder from the `PAGEINDEX_USER_TEST_DIR` environment variable and `pytest.skip` when it is unset or missing. For every `.md`/`.markdown` file: lossless round trip, no break inside protected blocks, contiguous line ranges, and mocked-LLM indexing that validates against the shared schema. For every `.pdf`: mocked-LLM standard indexing and offline Flash both validate against the schema. These tests are extra: no FR depends on them for its required coverage (Constitution IV), and the folder's documents are never copied into the repo (Constitution VI)

**Checkpoint**: PDF path verified unchanged

---

## Phase 6: User Story 3 - Submit and chat with a Markdown document (Priority: P2)

**Goal**: Markdown works end to end in the local client, tools and chat, with line-range citations

**Independent Test**: Submit `all_blocks.md` (LLM mocked) → structure → page content → chat answer
with a citation that includes lines

### Tests for User Story 3 ⚠️ (write first, must fail)

- [X] T038 [P] [US3] `test_submit_md` and `test_default_mode_standard` (meta `mode == "standard"`, `source_type == "markdown"`, `pageNum` == page count) in `tests/test_markdown_client.py`
- [X] T039 [P] [US3] `test_flash_rejected` ("Flash mode supports PDF only; Markdown uses standard mode"), `test_unsupported_type_rejected` ("only PDF and Markdown (.md, .markdown) files are supported in local mode."), `test_blank_md_rejected`, `test_bad_encoding_rejected` (`latin1.md`), and `test_headings_indexer_output_not_accepted` (FR-016: the client never loads `md_to_tree` output as a document) in `tests/test_markdown_client.py`
- [X] T040 [P] [US3] `test_stored_pages_exact`: `get_ocr(format="page")` items have `markdown`, `line_start`, `line_end`; joined `markdown` equals the file; `get_ocr(format="raw")` equals the file exactly, in `tests/test_markdown_client.py`
- [X] T041 [P] [US3] `test_tools_work`: `get_document`, `get_document_structure`, `get_page_content`, `get_tree` via `pageindex.agent_tools.call_tool` return the right sections and exact text, in `tests/test_markdown_client.py`
- [X] T042 [P] [US3] `test_citation_line_ranges`: an answer containing `<cite doc="all_blocks.md" page="2"/>` → `get_citations` entry has `line_start`/`line_end` of page 2; `resolve_citations` renders `[all_blocks.md, p. 2, lines A–B]`, in `tests/test_markdown_client.py`
- [X] T043 [P] [US3] `test_claude_code_rejected_for_md`: a `claude-code/` model raises the existing "flash mode only" error, in `tests/test_markdown_client.py`

### Implementation for User Story 3

- [X] T044 [US3] In `pageindex/local_api.py::submit_document`: accept `.md`/`.markdown` (update the non-PDF error text); if Markdown and `mode == "flash"` raise the Flash error; if Markdown and `mode is None` use `"standard"`; summary-only flash options keep their existing check
- [X] T045 [US3] In `pageindex/local_api.py`: make `_extract_page_texts` return `MarkdownPage` data for Markdown (via `get_markdown_pages`), feed `[(p.text, p.tokens)]` into `_index_standard` without recounting, map blank-file ValueError to "Failed to submit document: Markdown has no content. The file is blank."
- [X] T046 [US3] In `pageindex/local_api.py`: store pages as `{"page_index", "markdown", "line_start", "line_end"}` for Markdown; set `meta["source_type"]`; make `get_ocr(format="raw")` join Markdown pages with `""` (PDF keeps `"\n\n"`); read missing `source_type` as `"pdf"`
- [X] T047 [US3] In `pageindex/client.py`: `get_citations` adds `line_start`/`line_end` for citations on Markdown documents (looked up from stored pages); `resolve_citations` renders them as `[doc, p. N, lines A–B]`; no change to `citation_prompt` or `agent_tools.py`
- [X] T048 [US3] Run `tests/test_markdown_client.py` and `tests/test_agent_tools.py`, `tests/test_client.py`, `tests/test_local_chat.py` until green

**Checkpoint**: All four user stories work independently

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T049 [P] Update `README.md` (Markdown support section: standard mode only, heading hint, `--md-indexer headings`) and `pageindex/config.yaml` comments
- [X] T050 [P] Update `Requirements.md` status and tick its acceptance criteria that are now met
- [X] T051 Run [quickstart.md](quickstart.md) section 1 (offline; the PDF regression is covered there by T035). Sections 2–4 need an API key: run them only if one is available and say which were skipped. Record results in `specs/001-unified-markdown-indexing/checklists/requirements.md` notes
- [X] T052 Constitution v1.1.0 re-check against the diff (`git diff upstream/main`): PDF files only gained the extension branch and `source_type`; the only Markdown-only code after text entry is named exceptions 1–3 of Principle III; no drive-by edits; LICENSE untouched
- [X] T053 Verify `tests/data/pdf_baseline/` holds only template names and hashes, with no third-party document text (Constitution VI)

---

## Dependencies & Execution Order

### Phase dependencies

- Setup (Phase 1) → Foundational (Phase 2) → US2 (Phase 3) → US1 (Phase 4) → US3 (Phase 6)
- US4 (Phase 5) can start after Phase 4 (needs `source_type`), in parallel with US3
- Polish (Phase 7) after all stories

### User story dependencies

- **US2 (P1)**: depends only on Foundational; independently testable
- **US1 (P1)**: depends on US2 (consumes pages)
- **US4 (P1)**: depends on US1's envelope change (T026, T028)
- **US3 (P2)**: depends on US1 and US2

### Within each story

- Tests first and failing → implementation → run tests green
- `pageindex/markdown_pages.py` tasks are sequential (same file); test files can be written in parallel

### Parallel opportunities

- T003, T004, T005 together
- All US2 tests T008–T013 and T054 together (same file, separate functions; can be split across people)
- US1 tests T018–T023 and T055 together; T057 after T026
- US4 (T035–T037, T056) alongside US3 tests (T038–T043)

## Parallel Example: User Story 1

```text
Task: "T018 helper tests in tests/test_markdown_helpers.py"
Task: "T019 same prompt sequence test in tests/test_markdown_pipeline.py"
Task: "T023 shared schema test in tests/test_tree_schema.py"
```

## Implementation Strategy

### MVP first

1. Phases 1–2
2. Phase 3 (US2): pager verified lossless
3. Phase 4 (US1) without the heading hint (T018–T030): Markdown indexes to the shared tree
4. **Stop and validate**: CLI run on `all_blocks.md`, schema passes, PDF suite green

### Incremental delivery

1. MVP above
2. US4 regression proof
3. Heading hint (T031–T034)
4. US3 client + chat + citations
5. Polish
