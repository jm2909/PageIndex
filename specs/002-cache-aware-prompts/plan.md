# Implementation Plan: Cache-Aware Prompt Layout for Indexing

**Branch**: `feature/cache-aware-prompts` (from Phase 1 commit `2ba037f`) |
**Date**: 2026-11-14 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/002-cache-aware-prompts/spec.md`

## Summary

Make standard-mode indexing cache-friendly without making it one conversation. First, record
token usage per prompt template for every run (both layouts), so the current cost profile,
especially the fix-up rounds, becomes visible. Then add an opt-in `prompt_layout: cache` in which
every call is an independent request: a shared, cached instruction block (≥ 512 tokens), a cached
document block (the whole document for outline drafting, fix-up and description; the page for
small checks), and a short uncached question. The two per-section page checks merge into one call,
each parallel step warms the cache with one call first, and the outline is drafted in one call
when the document fits. A harness script compares both layouts on cost, time, tree quality and
LLM-judged golden-set answers and gives a verdict. Default behaviour stays byte-identical.

## Technical Context

**Language/Version**: Python ≥ 3.11 (venv 3.12)

**Primary Dependencies**: existing only: LiteLLM (provider calls, `cache_control` pass-through,
price map), PyYAML. No new runtime dependency.

**Storage**: local file store (unchanged); harness writes `Output/`, `Token_usage/v2/` (v1 = Phase 1 runs)

**Testing**: pytest with the Phase 1 fake LLM (`tests/fake_llm.py`) extended for the cache layout
(system/document/question blocks, the merged placement reply, simulated cache usage fields)

**Target Platform**: macOS / Linux, library + CLI + workspace harness scripts

**Project Type**: Python library with CLI; separate harness scripts in the workspace root

**Performance Goals**: cache layout ≥ 40% lower input spend on the three example Markdown files vs the measured baseline (SC-002);
indexing time ≤ +10% (SC-003); ≥ 50% of input tokens as cache reads (SC-004)

**Constraints**: default layout byte-identical to today (Constitution I, after amendment); same
prompts for PDF and Markdown (III); offline tests (IV); small, rebase-friendly edits (V)

**Scale/Scope**: 1 new module (`cache_layout.py`), edits in `utils.py`,
`page_index_classic.py`, `local_api.py`, `client.py` (option pass-through), `run_pageindex.py`,
`config.yaml`; 3 new test files; 1 new and 1 extended harness script

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status (pre) | Status (post-design) |
| --- | --- | --- | --- |
| I. PDF Behaviour Unchanged | Default prompts, calls and output identical | PASS under constitution v1.2.1 (amended 2026-11-14, T002): the opt-in layout and the additive top-level `usage_by_template` result key are on Principle I's allowed list; `usage` keeps its upstream shape | PASS: default path unchanged (`layout_blocks=None`, template names don't touch prompt text); `test_pdf_unchanged` stays green |
| II. Markdown Formatting Preserved | Pages stay exact; LLM copy only gets shared redaction | PASS | PASS: blocks are built from the same `_secure_doc_text` output; stored pages untouched |
| III. One Indexing Path | Same prompts for PDF and Markdown | PASS | PASS: layout dispatch is on `opt.prompt_layout`, never on format; test FR-012 |
| IV. Tests for Every Requirement | Offline test per FR | PASS | PASS: R10 map; the real-API comparison is a harness run, not a test |
| V. Upstream-Friendly | Small isolated changes | PASS (with care) | PASS: layout code in one new module; call sites get a guarded branch + `llm_template(...)` line each |
| VI. Licence & Attribution | Unchanged | PASS | PASS |

## Project Structure

### Documentation (this feature)

```text
specs/002-cache-aware-prompts/
├── plan.md              # This file
├── research.md          # Phase 0 decisions (R1–R10)
├── data-model.md        # templates, usage record, setting, call layout, memo, report
├── quickstart.md        # validation guide
├── contracts/
│   ├── prompt-layout.md # transport keyword, layout module, dispatch table, usage
│   └── harness-cli.md   # setting surfaces, index_documents.py, compare_layouts.py
├── checklists/requirements.md
└── tasks.md             # /speckit-tasks output
```

### Source Code

```text
PageIndex/
├── pageindex/
│   ├── cache_layout.py        # NEW: SYSTEM_BLOCK, whole_document_block, page_block, question(),
│   │                          #      warm_then_gather, placement memo
│   ├── utils.py               # llm_template(); _add_usage per-template; layout_blocks keyword in
│   │                          #   llm_completion / llm_acompletion; summary + description dispatch
│   ├── page_index_classic.py  # template names; cache-layout dispatch per contracts table;
│   │                          #   page_index(prompt_layout=)
│   ├── local_api.py, client.py# prompt_layout index option → opt
│   └── config.yaml            # + prompt_layout: "standard"
├── run_pageindex.py           # --prompt-layout
└── tests/
    ├── fake_llm.py            # extended: cache layout templates, merged reply, cache usage fields
    ├── test_usage_by_template.py   # NEW
    ├── test_prompt_layout.py       # NEW
    └── test_compare_layouts.py     # NEW (harness logic with recorded fixtures)

(workspace root)
├── index_documents.py         # + --prompt-layout, by_template, cost_usd, per-layout stores
└── compare_layouts.py         # NEW: both layouts, golden questions, LLM judge, verdict
```

**Structure Decision**: library changes stay in `PageIndex/` behind the setting; real-API
measurement stays in the workspace harness next to `index_documents.py` and `compare_trees.py`.

## Complexity Tracking

No open violations. The Principle I change (opt-in layout, additive usage field) was resolved by
amending the constitution to v1.2.0 (T002). For the record: caching needs a stable shared prefix;
today's prompts put varying text first and their fixed parts are below the 512-token minimum; a
Markdown-only layout would break Principle III, and automatic caching without reordering adds
write cost with no reads (R2).
