# Research: Unified Markdown Indexing

All Technical Context items were resolved from the codebase; no NEEDS CLARIFICATION remain.

## R1. Where Markdown enters the pipeline

- **Decision**: Dispatch by extension in `utils.get_page_tokens` (`utils.py:970`, the only call
  site is `page_index_classic.py:1269`) and in `LocalAPI._extract_page_texts`
  (`local_api.py:241`, feeds `page_index_main(..., page_list=...)` at `local_api.py:252`).
- **Rationale**: Both already return/produce the `[(text, tokens)]` list everything downstream
  uses. `extract_text_from_pdf`, `get_pdf_title`, `get_text_of_pages`, `get_number_of_pages` are
  unused upstream, so their Markdown counterparts are added for parity (FR-002) but are not the hook.
- **Alternatives**: a new `load_pages()` entry point (rejected: extra indirection and more
  upstream call sites changed); a wrapper outside the package (rejected: client and CLI wouldn't
  accept `.md`).

## R2. Markdown block detection for the pager

- **Decision**: A single-pass line scanner in `pageindex/markdown_pages.py` that labels each line
  with the block it belongs to and marks *safe break points* (positions between lines not inside a
  protected block). Rules:
  - Front matter: only if line 1 is `---` (YAML) or `+++` (TOML); ends at the next matching line.
  - Fenced code: opening line matches `^ {0,3}(`{3,}|~{3,})`; closes on a line with the same
    character and at least as many; unclosed fence runs to end of file.
  - Table: a run of consecutive lines whose stripped form starts with `|`, or a header line
    followed by a delimiter row matching `^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$`.
  - List: a line starting with `^\s{0,3}([-*+]|\d{1,9}[.)])\s`, continuing through indented
    lines and single blank lines followed by indented or list lines.
  - Blockquote: consecutive lines starting with `^\s{0,3}>`.
  - HTML block: a line starting with `^\s{0,3}<(?!https?:)[A-Za-z!/?]`, until the next blank line.
  - Headings: ATX `^\s{0,3}#{1,6}(\s|$)`; setext = non-blank text line followed by `^=+\s*$` or
    `^-+\s*$` (the pair is kept together).
- **Rationale**: No new dependency (Constitution V); only block *boundaries* are needed, not a
  full parse. CommonMark-style patterns cover the protected blocks in FR-004.
- **Alternatives**: `markdown-it-py` (accurate token map with line numbers, but a new runtime
  dependency for a boundary-only need); `mistune` (no reliable line mapping).

## R3. Page building and token budget

- **Decision**: Greedy packing. Walk safe break points; keep adding segments (the text between
  consecutive safe breaks) while the page stays ≤ `md_page_tokens` (default 800). When the next
  segment would overflow, close the page at the best break inside the current page window
  preferring (1) just before a heading, (2) a blank line, (3) any safe break. A segment larger
  than the budget becomes its own page; a segment larger than `max_token_num_each_node` (20,000)
  is split at line boundaries with a `logging.warning`.
- Tokens are counted with the pipeline's own `count_tokens(text, model)` (LiteLLM
  `token_counter`), once per segment, so page tokens add up consistently.
- Splitting works on `str.splitlines(keepends=True)` after reading with `newline=""`, so `\r\n`
  and mixed endings are preserved and `"".join(pages) == file_text` holds exactly.
- Whitespace-only trailing/leading runs attach to the neighbouring page (never dropped).
- **Alternatives**: fixed line counts (ignores tokens); splitting on headings only (pages vary
  wildly, breaks the 20-page TOC scan and 10-page node limits).

## R4. Heading hint (FR-017)

- **Decision**: When `md_heading_hint` is on, build a TOC list
  `[{structure, title, physical_index}]` from ATX/setext headings (outside code/front matter) with
  `physical_index` = the page the heading starts on, then call `meta_processor` with a new mode
  `process_toc_hint`, which skips TOC extraction and goes straight to the shared
  `validate_and_truncate_physical_indices` → `verify_toc` → `fix_incorrect_toc_with_retries`
  steps. On low verification accuracy it falls back to `process_no_toc`, like the existing modes.
- Headings are extracted from the pipeline's `page_list` texts (`extract_heading_toc(page_list)`),
  because `tree_parser` never sees `MarkdownPage` objects; fence and front-matter state is carried
  across page boundaries.
- When the hint is on and the heading list is non-empty, `tree_parser` **skips `check_toc`**
  (no `toc_detector_single_page` calls) and calls `meta_processor` with `process_toc_hint`
  directly; that skip is where the saving in SC-008 comes from. An empty heading list (no
  headings) runs the normal path unchanged.
- `meta_processor` gets an explicit `elif mode == 'process_toc_hint'` (set the list as
  `toc_with_page_number`) and an explicit fallback branch
  `elif mode == 'process_toc_hint': return await meta_processor(..., mode='process_no_toc', ...)`,
  so an unknown mode never silently becomes `process_no_toc`.
- `structure` numbers come from heading levels (`1`, `1.1`, `1.2`, `2`, ...); skipped levels are
  normalised to the nearest parent.
- **Rationale**: Reuses verification so wrong hints are corrected by the same LLM checks.
- **Alternatives**: rendering a fake TOC page (changes LLM input; rejected); skipping
  verification (no safety net; rejected).

## R5. Citations with line ranges (FR-012)

- **Decision**: Keep the citation prompt unchanged; the LLM cites `doc` + `page` as for PDF.
  `PageIndexClient.get_citations` adds `line_start`/`line_end` to each citation for a Markdown
  document by looking up the cited page in the stored pages; `resolve_citations` renders them as
  `[notes.md, p. 3, lines 120–164]`.
- **Rationale**: Changing the prompt per format would break Principle III and FR-007.
- **Alternatives**: ask the LLM to cite lines (format-specific prompt, unreliable numbers).

## R6. Shared schema test

- **Decision**: `contracts/tree-output.schema.json` (JSON Schema draft 2020-12) validated in
  tests with `jsonschema`, added as a dev dependency only.
- **Alternatives**: hand-written dict checks (less precise, duplicated across tests).

## R7. Requirement → test map

| FR | Test |
| --- | --- |
| FR-001 | `test_markdown_client.py::test_submit_md`, `test_markdown_pipeline.py::test_cli_md_standard`, `::test_library_call_md_options` |
| FR-002 | `test_markdown_helpers.py` (one test per helper) |
| FR-003 | `test_markdown_pages.py::test_budget_and_preferred_breaks` |
| FR-004 | `test_markdown_pages.py::test_no_break_inside_protected_blocks`, `::test_oversized_block_warning` |
| FR-005 | `test_markdown_pages.py::test_lossless_round_trip` (all fixtures, incl. CRLF) |
| FR-006 | `test_markdown_pages.py::test_line_ranges` |
| FR-007 | `test_markdown_pipeline.py::test_same_prompt_sequence_pdf_vs_md` |
| FR-008 | `test_tree_schema.py` |
| FR-009 | `test_markdown_pipeline.py::test_node_line_ranges` |
| FR-010 | `test_markdown_client.py::test_stored_pages_exact` |
| FR-011 | `test_markdown_client.py::test_tools_work` |
| FR-012 | `test_markdown_client.py::test_citation_line_ranges` |
| FR-013 | `test_markdown_client.py::test_default_mode_standard`, `::test_flash_rejected` |
| FR-014 | `test_markdown_pages.py::test_whitespace_only_rejected`, `test_markdown_pages.py::test_bad_encoding`, `test_markdown_helpers.py::test_unsupported_extension`, `test_markdown_client.py::test_unsupported_type_rejected` |
| FR-015 | full existing suite + `test_markdown_pipeline.py::test_pdf_unchanged` |
| FR-016 | `test_page_index_md.py` (existing) + `test_markdown_pipeline.py::test_cli_md_indexer_headings` |
| FR-017 | `test_markdown_pipeline.py::test_heading_hint_fewer_calls`, `::test_hint_off_identical`, `::test_library_call_md_options` |
| FR-018 | `test_markdown_pipeline.py::test_redaction_prompt_only` |
