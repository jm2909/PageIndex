---

description: "Task list for Cache-Aware Prompt Layout for Indexing"
---

# Tasks: Cache-Aware Prompt Layout for Indexing

**Input**: Design documents from `specs/002-cache-aware-prompts/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: Required (Constitution IV). Written first, must fail before implementation, LLM mocked
with `tests/fake_llm.py`. Real-API steps are harness runs, never part of `pytest`.

**Paths**: library paths are relative to `PageIndex/`; harness paths (`index_documents.py`,
`compare_layouts.py`, `Output/`, `Token_usage/`) are relative to the workspace root
(`vectorlessRAG/`).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependencies)
- **[Story]**: US1–US4 from [spec.md](spec.md)

---

## Phase 1: Setup

- [X] T001 With the owner's go-ahead, commit Phase 1 (code, tests, `specs/001-…`; not `Requirements.md`, dot-folders, `specs/002-…` or `examples/` additions) on `feature/unified-tree-schema` (done: `2ba037f`), then create `feature/cache-aware-prompts` from it (done, 2026-11-14)
- [X] T002 Amend `.specify/memory/constitution.md` via `/speckit-constitution` to v1.2.0 (MINOR): Principle I allows an opt-in, off-by-default prompt layout that changes prompts for both formats only when enabled (default stays byte-identical to upstream; applied identically to PDF and Markdown) and allows the additive `usage["by_template"]` field on every run; Sync Impact Report + Last Amended date (FR-017, research R9)
- [X] T003 Add `prompt_layout: "standard"` to `pageindex/config.yaml` with a comment: values `standard` / `cache`, standard mode only, no effect on Flash
- [X] T004 (needs the owner's approval: real API call, tiny spend) Confirm LiteLLM's Anthropic usage fields with ONE live call (harness script `tests/tools/probe_cache_usage.py`, reads the workspace `.env`, prints only field names and numbers): send the same >512-token system block twice with `cache_control`, record which of `usage.prompt_tokens_details.cache_write_tokens` / `usage.cache_creation_input_tokens` / `usage.prompt_tokens_details.cached_tokens` / `usage.cache_read_input_tokens` are filled and whether `prompt_tokens` includes cached tokens; write the result into research.md R3 "Open check" (resolves analysis A5)

---

## Phase 2: Foundational

**⚠️ No user story work before this phase is complete**

- [X] T005 Extend `tests/fake_llm.py`: accept `layout_blocks=` on `completion`/`acompletion`, record `(template, system, document, question)` per call, recognise cache-layout tasks by the task name in the question, answer `placement_check` with `{"appears","starts_at_top"}`, `outline_whole` like `generate_toc_init` over the whole-document block, `toc_index_fixer` with the page named in the question; return simulated usage (`prompt_tokens`, `cached_tokens` when the system/document block was seen before in the run, `cache_write_tokens` on first sight) so usage tests run offline
- [X] T006 Add `prompt_layout` plumbing (no behaviour yet): `run_pageindex.py --prompt-layout {standard,cache}` (error with `--mode flash`: "--prompt-layout applies to standard mode only"); `page_index(..., prompt_layout=None)` in `pageindex/page_index_classic.py`; `prompt_layout` index option in `pageindex/types.py::LocalIndexConfig`, `pageindex/client.py` → `LocalAPI(prompt_layout=...)` → `opt` in `pageindex/local_api.py::_index_standard`

**Checkpoint**: setting reaches `opt`; fake LLM understands both layouts

---

## Phase 3: User Story 1 - See where indexing tokens go (Priority: P1) 🎯 MVP

**Goal**: per-template usage for every standard-mode run, both layouts

**Independent Test**: index a fixture (fake LLM), per-template record returned (and saved by the harness); calls and token sums equal the totals

### Tests for User Story 1 (write first, must fail)

- [X] T007 [P] [US1] `tests/test_usage_by_template.py`: `test_by_template_sums_equal_totals` (PDF and Markdown, standard layout: each numeric field summed over templates equals `usage` totals; `calls` equals fake-LLM call count); `test_fix_up_calls_counted` (fake LLM with `verify_no_first` forces fix-ups; `toc_index_fixer` present with the right count); `test_unnamed_calls_go_to_other`; `test_prompts_unchanged_by_template_names` (standard layout prompt hashes equal the Phase 1 PDF baseline `tests/data/pdf_baseline/baseline.json` via `tests/tools/capture_pdf_baseline.capture`)

### Implementation for User Story 1

- [X] T008 [US1] In `pageindex/utils.py`: add context var `_llm_template` and context manager `llm_template(name)`; in `_add_usage` also add the call to a separate per-template dict (context var `_llm_usage_by_template`, returned by `LocalAPI.submit_document` as top-level `usage_by_template`; `usage` keeps its shape) under `name or "other"` with fields `calls, prompt_tokens, completion_tokens, cached_tokens, cache_write_tokens`; read cache fields per the T004 result (both spellings, first non-zero wins)
- [X] T009 [US1] Wrap every model call in `pageindex/page_index_classic.py` with `llm_template(...)` using the names in [data-model.md](data-model.md) "Prompt template names" (`toc_detector`, `toc_extraction`, `outline_init`, `outline_continue`, `check_title_appearance`, `check_title_start`, `toc_index_fixer`, `add_page_number`); no prompt text changes
- [X] T010 [US1] Wrap summary and description calls in `pageindex/utils.py` (`SummaryScheduler` leaf/parent → `leaf_summary`/`parent_summary`, `generate_node_summary` → `node_summary`, `generate_doc_description` → `doc_description`)
- [X] T011 [US1] Harness `index_documents.py`: write `by_template`, `prompt_layout` and `cost_usd` (from `litellm.model_cost` prices: uncached input × input price + cache writes × write price + cache reads × read price + output × output price, per the T004 field semantics) into the per-run JSON, and append `prompt_layout,cost_usd` columns at the end of `token_usage.csv` (Phase 2 runs: `Token_usage/v2/`) (older rows stay readable)
- [X] T012 [US1] Run `tests/test_usage_by_template.py` and the full suite until green

**Checkpoint**: per-template usage visible for today's layout (quickstart §2)

---

## Phase 4: User Story 2 - Index with the cache-aware layout (Priority: P1)

**Goal**: opt-in layout per [contracts/prompt-layout.md](contracts/prompt-layout.md)

**Independent Test**: an example pair (`PageIndex/examples`) with layout on (fake LLM): three-part calls, correct scopes, warm-first, merged check, cache reads in the record

### Tests for User Story 2 (write first, must fail)

- [ ] T013 [P] [US2] `tests/test_prompt_layout.py`: `test_setting_default_off`, `test_flash_ignores_layout`, `test_three_part_layout` (system, document, question in order; no earlier call's question/answer in any call), `test_system_block_cacheable_size` (`count_tokens(SYSTEM_BLOCK) >= 512`), `test_system_block_identical_across_calls`
- [ ] T014 [P] [US2] Same file: `test_document_scope_by_template` (whole document for `outline_whole`, `toc_index_fixer`, `add_page_number`, `doc_description`; page for `toc_detector`, `toc_extraction`, `placement_check`, `leaf_summary`), `test_whole_doc_block_identical` (byte-identical across whole-doc calls), `test_redaction_applied_to_blocks` (injection fixture: `[REDACTED]` in the document block, stored pages unchanged)
- [ ] T015 [P] [US2] Same file: `test_merged_placement_check_one_call_per_section` (no `check_title_appearance`/`check_title_start` templates; start check served from the memo; a fix-up-changed page triggers one extra `placement_check`), `test_outline_single_call_when_fits`, `test_outline_falls_back_when_too_big` (patch the model's input limit low → `outline_init`/`outline_continue` used and logged)
- [ ] T016 [P] [US2] Same file: `test_warm_first_then_parallel` (fake LLM records start/finish order: first call of each step finishes before the others start), `test_warm_failure_still_runs_rest`, `test_cache_markers_present` (system + document blocks carry `cache_control`), `test_no_cache_provider_still_indexes` (fake drops markers; tree validates), `test_same_template_sequence_pdf_vs_md_cache_layout` (page-matched pair as in Phase 1 T019), `test_cache_layout_tree_validates_schema`

### Implementation for User Story 2

- [ ] T017 [US2] In `pageindex/utils.py`: add `layout_blocks=None` to `llm_completion` and `llm_acompletion`; when given, build `[system(cache_control), user[document(cache_control) if any, question]]` (+ `chat_history` after them for continuations) per the contract; `None` keeps today's request bytes
- [ ] T018 [US2] Create `pageindex/cache_layout.py`: `LayoutBlocks`, `SYSTEM_BLOCK` (hardening text + job statement + one numbered section per task in `TASKS` with its reply format; `placement_check` reply `{"thinking","appears","starts_at_top"}`), `whole_document_block(page_list, start_index=1)` (pages wrapped `<physical_index_N>`…`<physical_index_N>` exactly as `process_no_toc` does, then `_secure_doc_text`; cached per run), `page_block(text)`, `question(task, **fields)`, `warm_then_gather(coros)`, placement memo keyed by (normalised title, page)
- [ ] T019 [US2] In `pageindex/page_index_classic.py`, dispatch on `opt.prompt_layout == "cache"` (never on format) per the contract table: `toc_detector_single_page` and TOC-reading steps (page scope); `process_no_toc` → `outline_whole` if `count_tokens(whole block)` + margin ≤ the model's `max_input_tokens` from `litellm.model_cost`, else current chunked path with a log line; `verify_toc` and `check_title_appearance_in_start_concurrent` → `placement_check` + memo; `fix_incorrect_toc` → `toc_index_fixer` on the whole-document block naming pages a–b; `process_none_page_numbers`/`add_page_number_to_toc` → whole-document block; use `warm_then_gather` where these steps gather
- [ ] T020 [US2] In `pageindex/utils.py`: `SummaryScheduler` leaf/parent prompts and `generate_doc_description` use the cache layout when the run's layout is `cache` (pass the layout through `summarize_tree`/`generate_doc_description` arguments from `page_index_main`); leaf summaries warm first
- [ ] T021 [US2] Run `tests/test_prompt_layout.py`, `tests/test_markdown_pipeline.py`, `tests/test_tree_schema.py` until green

**Checkpoint**: cache layout indexes PDF and Markdown with identical template sequences (quickstart §3 offline part)

---

## Phase 5: User Story 4 - Current behaviour unchanged by default (Priority: P1)

**Goal**: prove the default layout is untouched

**Independent Test**: full suite + PDF baseline with the layout off

- [ ] T022 [P] [US4] In `tests/test_prompt_layout.py`: `test_default_layout_matches_baseline` (layout absent and `"standard"` both reproduce `tests/data/pdf_baseline/baseline.json` templates, prompt hashes and output hash; `usage` has its upstream shape; `usage_by_template` is the only new result key)
- [ ] T023 [US4] Run the full suite `pytest -q`; fix regressions in touched files only; confirm `test_pdf_unchanged` unchanged and green

**Checkpoint**: default path verified

---

## Phase 6: User Story 3 - Decide on evidence (Priority: P2)

**Goal**: `compare_layouts.py` per [contracts/harness-cli.md](contracts/harness-cli.md)

**Independent Test**: harness logic on recorded fixtures (no API) produces both layouts' metrics and the verdict

### Tests for User Story 3 (write first, must fail)

- [ ] T024 [P] [US3] `PageIndex/tests/test_compare_layouts.py` (imports the harness module from the workspace root via path): `test_cost_math` (known usage → expected `cost_usd` from a stubbed price map), `test_verdict_rule` (overall drop ≤ 1.5 on 30 AND per-document drop ≤ 1 AND cost or time lower → `win`; per-document drop 1.5 → `no win`; quality OK but cost and time worse → `no win`), `test_judge_parsing` (valid JSON, retry once on garbage, then `wrong` with reason "unparseable judge reply"), `test_sc002_target_reported` (met / missed shown, not in verdict), `test_same_chat_model_both_layouts_recorded` (FR-018)

### Implementation for User Story 3

- [ ] T025 [US3] Harness `index_documents.py`: add `--prompt-layout {standard,cache}` (default `standard`); cache-layout stores at `Output/<format>_based/store_cache`; pass `index={"prompt_layout": ...}` to `PageIndexLocalClient`; manifest records layout per entry
- [ ] T025a [US3] Harness `index_examples.py` (owner request, 2026-11-14): add `--prompt-layout {standard,cache}`; token usage for both layouts goes to `Token_usage/v2/` (owner, 2026-11-14; `--usage-dir` default already v2; rows carry `prompt_layout`, `document_id` = golden id); cache-layout trees saved as `<name>_structure_cache.json` beside the standard ones in `PageIndex/examples/results/{documents,markdown}/`; add a standard-vs-cache section to `PageIndex/examples/results/comparison.md` (cost, time, tokens by type, cache-read share, sections matching)
- [ ] T026 [US3] Create harness `compare_layouts.py` (workspace root): flags `--doc {DC_COL_10,LAB_SVC_10,SOLAR_OM_10,all}` (documents and questions from `golden_qa_30.csv`: `document_pdf`, `document_markdown`, `expected_answer`, `supporting_clauses`, `source_pdf_pages`, `source_markdown_section`), `--formats`, `--judge-model`, `--chat-model` (default the `.env` model, same for both layouts), `--skip-index`, `--questions N`; per document × format: index both layouts (reuse stores with `--skip-index`), collect seconds, tokens by type, `cost_usd`, sections found and start-page agreement (reuse `compare_trees.py` functions; reference = PDF standard tree), answer the document's golden questions with `client.chat(question, doc_id=...)` for each index, grade with the judge (prompt includes golden answer + evidence excerpt; JSON reply), save per-question verdict + reason; report the cache-read share of input tokens per run with a met/missed line for SC-004 (≥ 50%), and seconds per pipeline step so the warming cost against SC-003 is visible; write `Output/comparison/layouts_<doc>.md` and `.json`; print verdict per the contract rule and whether the SC-002, SC-003 and SC-004 targets were met
- [ ] T027 [US3] Run `PageIndex/tests/test_compare_layouts.py` until green

**Checkpoint**: comparison ready to run with real API (quickstart §4)

---

## Phase 7: Polish & Cross-Cutting

- [ ] T028 [P] Update `README.md` (Markdown section: `prompt_layout: cache` opt-in, what it changes, how to measure) and `pageindex/config.yaml` comment
- [ ] T029 [P] Update `Requirements.md` with a Phase 2 status line
- [ ] T030 Run quickstart §1 offline and record results in `specs/002-cache-aware-prompts/checklists/requirements.md` notes; with the owner's approval of the API spend, run quickstart §3–§4 on the three example pairs (§2 done 2026-11-14) and record cost/time/score and the verdict
- [ ] T031 Constitution v1.2.0 re-check against the diff: default path byte-identical; layout dispatch never on format; one new module; LICENSE untouched

---

## Dependencies & Execution Order

- Setup (T001–T004) → Foundational (T005–T006) → US1 (T007–T012) → US2 (T013–T021) → US4 (T022–T023) → US3 (T024–T027) → Polish
- T002 (amendment) must precede T017–T020 (layout code); T004 must precede T005, T008 and T011 (field semantics)
- If T030 shows SC-003 missed because of warming, warm only the steps that share a whole-document block (outline, fix-up, description) and re-measure
- US2 depends on US1's template names (T009–T010) for its usage assertions
- US4 can run as soon as US2 is done; US3 needs US1 (usage/cost) and US2 (cache layout)

## Parallel Opportunities

- T003 with T004; T005 with T006
- US2 tests T013–T016 (same file, separate functions; can be split across people)
- T022 alongside US3 tests T024; T028 with T029

## Parallel Example: User Story 2

```text
Task: "T013 setting and system-block tests in tests/test_prompt_layout.py"
Task: "T014 document-scope tests in tests/test_prompt_layout.py"
Task: "T016 warming and marker tests in tests/test_prompt_layout.py"
```

## Implementation Strategy

### MVP first

1. Setup + Foundational
2. US1: per-template usage on today's layout → run quickstart §2 on the example pairs to see where tokens go (done 2026-11-14: page checks dominate)
3. **Stop and review**: confirm the fix-up step is the main cost before building the layout

### Incremental delivery

1. MVP above
2. US2 cache layout (offline-tested), then US4 default check
3. US3 comparison, then the real-API verdict run (owner approves spend)
