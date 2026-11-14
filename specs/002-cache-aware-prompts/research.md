# Research: Cache-Aware Prompt Layout for Indexing

Facts were checked against the code and the installed LiteLLM (1.105.x) on 2026-11-14.

## R1. How calls reach the model today

- **Decision**: Keep `llm_completion(model, prompt, chat_history=None, return_finish_reason=False)`
  and `llm_acompletion(model, prompt, **params)` unchanged for the current layout, and add an
  optional keyword path, `layout_blocks=` (system text plus ordered user blocks, each with a
  "cache" flag), used only by the cache-aware layout. When it is given, the wrappers build
  `[{"role": "system", ...}, {"role": "user", "content": [blocks]}]` with
  `cache_control: {"type": "ephemeral"}` on the system block and on the document block.
- **Rationale**: Every call today is one user string with no system message
  (`utils.py:560`, `:618`), so nothing can be cached. Adding a keyword keeps every current call
  byte-identical (Constitution I) and touches two functions instead of every call site's
  transport.
- **Alternatives**: a new transport module (more code to rebase); passing raw `messages` from call
  sites (leaks provider details into the pipeline).

## R2. Caching on the configured provider

- **Decision**: Explicit `cache_control` breakpoints on content blocks (at most 2 per call: system,
  document), 5-minute default lifetime.
- **Facts**: LiteLLM's map lists `anthropic/claude-haiku-5-5` with input $1e-7, cache write
  $1.25e-7, cache read $1e-8 per token, 1M input context. Minimum cacheable prefix on Haiku 5.5 is
  512 tokens; max 4 breakpoints per request. `utils._cache_off` returns `{}` for this model
  (LiteLLM's OpenAI breakpoint rule is False for it), so it does not interfere. A test document
  indexes in 1–2 minutes, inside the 5-minute lifetime.
- **Providers without explicit caching** (OpenAI-style automatic caching): the system and
  document blocks still come first, so automatic prefix caching benefits; `cache_control` is
  dropped by LiteLLM where unsupported (`drop_params=True` is already sent).
- **Alternatives**: 1-hour lifetime (2× write price, no benefit for a 2-minute run); automatic
  top-level caching (would put the breakpoint after the unique question: pure write surcharge).

## R3. Recording usage per template

- **Decision**: A context variable `_llm_template` set by a small context manager
  `llm_template(name)` around each prompt function's model call; `_add_usage` also adds the call's
  numbers to a separate per-template dict (context variable `_llm_usage_by_template`), which
  `LocalAPI.submit_document` returns as the top-level `usage_by_template` key; `usage` keeps its
  upstream shape (an upstream test checks it exactly; owner's decision, 2026-11-14).
  Both layouts set template names, so the breakdown exists for the current layout too (FR-001).
- **Rationale**: `_add_usage` (`utils.py:65`) already sums `prompt_tokens_details.cached_tokens`
  and `cache_write_tokens` per call; a per-template bucket is a small addition. Context variables
  propagate into the `asyncio` tasks the pipeline creates. Prompt text is not changed.
- **Checked live (T004, 2026-11-14, `tests/tools/probe_cache_usage.py`, claude-haiku-5-5)**:
  LiteLLM fills `prompt_tokens_details.cache_write_tokens` (also `cache_creation_input_tokens`) on
  the writing call and `prompt_tokens_details.cached_tokens` (also `cache_read_input_tokens`) on
  the reading call: exactly the fields `_add_usage` already reads, so no change is needed there.
  `prompt_tokens` **includes** both (3,546 = 18 uncached + 3,528 cached), so
  uncached input = `prompt_tokens − cached_tokens − cache_write_tokens` (R7 cost formula).
- **Tokenizer gap**: LiteLLM's local `token_counter` estimated the probe's system block at 2,217
  tokens; Anthropic counted 3,528 (~1.6×). Size checks that matter for Claude (the 512-token
  cacheable minimum in FR-005, "whole document fits" in FR-009) MUST keep a safety margin or use
  the provider's count; the FR-005 test asserts ≥ 512 on the local estimate, which is conservative.
- **Alternatives**: matching template names from prompt text (brittle, breaks when prompts change).

## R4. Shared instruction block

- **Decision**: One system text per run, identical for every call, holding: the existing safety
  hardening text, a short statement of the indexing job, and a numbered section per task
  (TOC detection, outline drafting, section placement check, fix-up, leaf summary, parent summary,
  document description) with its reply format. Each call's question names its task by number.
- **Rationale**: Today's fixed prefixes are 49–348 tokens, below Haiku 5.5's 512-token minimum;
  the combined instructions are ~1.5–2K tokens, so the system block caches on its own and every
  call gets a cache read of it (FR-005). A unit test asserts its token count ≥ 512.
- **Alternatives**: one system block per task (each below the minimum, no cross-task sharing).

## R5. Document scope per call type

- **Decision**:
  - Whole-document block = the pages wrapped exactly as `process_no_toc` wraps them today
    (`<physical_index_N>` … `<physical_index_N>`), passed through the same redaction/wrapping
    (`_secure_doc_text`), built once per run and reused byte for byte. Used by outline drafting,
    fix-up and document description.
  - Page block = the page text through `_secure_doc_text`, used by TOC detection, the merged
    placement check and leaf summaries.
- **Measured baseline** (current layout, the 3 golden-set pairs, 2026-11-14): the two placement
  checks are 72% (PDF) / 82% (Markdown) of input tokens, 240 calls over 3 documents; a Markdown page
  (~800 tokens) is re-sent about 13 times; no fix-ups. So page-scoped caching plus the merged
  check (R6) carry most of the saving on these documents.
- **Cost reasoning** (office lease, measured in Phase 1): whole document ≈ 45–60K tokens. Reading it
  from cache costs ≈ 4.5–6K token-equivalents per call, cheaper than today's fix-up calls (which
  resend multi-page spans) but far more than today's ~700-token page checks; so small calls keep
  page scope.
- **Alternatives**: whole document for every call (≈ 1.5M token-equivalents for ~300 page calls vs
  ≈ 240K today); page spans for fix-up as today (no reuse across fix-up calls).

## R6. Merged placement check and warming

- **Decision**: One call per (section title, page) returns
  `{"appears": "yes|no", "starts_at_top": "yes|no"}`. `verify_toc` uses `appears`;
  `check_title_appearance_in_start_concurrent` reads `starts_at_top` from a per-run memo keyed by
  (title, page) and calls the model only on a memo miss (a title or page the fix-up changed).
- **Warming**: in each step that gathers calls sharing a cached block (merged checks, fix-up, leaf
  summaries, TOC detection), await the first call, then gather the rest; if the first call raises,
  the rest still run (FR-010).
- **Whole-document outline**: one call when the document block fits the configured model's input
  limit (from LiteLLM's map, minus a margin for instructions and output); else today's chunked
  `generate_toc_init` / `generate_toc_continue` path, logged (FR-009).
- **Alternatives**: no memo (would not reduce calls); warming via a separate zero-output request
  (extra call, adds latency).

## R7. Comparison and grading

- **Decision**: A harness script beside `index_documents.py` (`compare_layouts.py`) that, per test
  document and format: indexes with each layout into a separate store, records time and the
  per-template usage, computes cost from LiteLLM's price map
  (uncached input × input price + cache writes × write price + cache reads × read price + output ×
  output price), compares trees with `compare_trees.py`'s start-page agreement, answers the golden
  questions with the existing local chat (unchanged), and grades each answer with an LLM judge
  (correct 1 / partly 0.5 / wrong 0; a question marked not answerable, if a future golden set has
  one, is correct when the answer says the document doesn't contain it). Verdicts and reasons are saved per question; the report states
  "win" only per FR-015/FR-016 (overall drop ≤ 5% of max, i.e. 1.5 points on 30; per document
  drop ≤ 1 point on 10). Both layouts answer with the same chat model and settings (FR-018).
- **Judge model**: defaults to the indexing model from `.env`, overridable with `--judge-model`;
  the judge prompt includes the golden set's `expected_answer`, `supporting_clauses` (clause
  names) and source page/section, and asks for JSON.
- **Rationale**: Keeps real-API, money-spending work out of the test suite (Constitution IV) and in
  the harness the user already runs.

## R8. Setting and plumbing

- **Decision**: Config key `prompt_layout: "standard"` (values `standard`, `cache`) in
  `config.yaml`; CLI flag `--prompt-layout {standard,cache}` (standard mode only); local client
  index option `prompt_layout` passed into `LocalAPI` and into the `opt` it builds; `page_index()`
  wrapper gains `prompt_layout=None`. Flash ignores it.
- **Alternatives**: environment variable (invisible in saved runs); separate entry point
  (duplicates the pipeline).

## R9. Constitution

- **Decision**: Amend Principle I (v1.1.0 → 1.2.0, MINOR) to allow an opt-in, off-by-default prompt
  layout that changes prompts for both formats when enabled, provided the default remains
  byte-identical to upstream and the layout is applied identically to PDF and Markdown; and to
  allow the additive per-template usage (top-level `usage_by_template`, v1.2.1) on every run. Done as
  the first implementation task via `/speckit-constitution`, before any layout code merges
  (FR-017).

## R10. Requirement → test map

| FR | Test (offline, fake LLM) |
| --- | --- |
| FR-001, FR-002 | `test_usage_by_template.py`: both layouts; sums equal totals; fix-up calls counted |
| FR-003 | `test_prompt_layout.py::test_setting_default_off`, `::test_flash_ignores_layout` |
| FR-004 | `::test_three_part_layout`, `::test_calls_independent` |
| FR-005 | `::test_system_block_cacheable_size` |
| FR-006, FR-007 | `::test_document_scope_by_template`, `::test_whole_doc_block_identical` |
| FR-008 | `::test_merged_placement_check_one_call_per_section` |
| FR-009 | `::test_outline_single_call_when_fits`, `::test_outline_falls_back_when_too_big` |
| FR-010 | `::test_warm_first_then_parallel`, `::test_warm_failure_still_runs_rest` |
| FR-011 | `::test_cache_markers_present`, `::test_no_cache_provider_still_indexes` |
| FR-012 | `::test_same_template_sequence_pdf_vs_md_cache_layout` |
| FR-013 | existing `test_pdf_unchanged` + full suite with layout off |
| FR-014–FR-016 | `test_compare_layouts.py` (harness logic with recorded fixtures: cost math, verdict rule, judge parsing) |
| FR-017 | constitution version check in T-final review (no code test) |
| FR-018 | `test_compare_layouts.py::test_same_chat_model_both_layouts_recorded` |
