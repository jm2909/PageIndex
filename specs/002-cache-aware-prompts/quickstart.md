# Quickstart: validating the cache-aware prompt layout

## 1. Offline (no API key)

```bash
cd PageIndex && source .venv/bin/activate
pytest tests/test_usage_by_template.py tests/test_prompt_layout.py tests/test_compare_layouts.py -q
pytest -q          # full suite: layout off must leave everything as before (incl. test_pdf_unchanged)
```

Expected: all pass. Requirement coverage: [research.md R10](research.md).

## 2. Per-template usage, current layout (real API, from the workspace root)

```bash
PageIndex/.venv/bin/python index_examples.py --force        # the 3 golden-set pairs
```

Expected: `Token_usage/v2/<format>_based/<DOC_ID>_*.json` contains `by_template` whose sums equal
the totals and `prompt_layout: standard`; fix-up calls, when any, appear under `toc_index_fixer`.
Done 2026-11-14: page checks are 72% (PDF) / 82% (Markdown) of input tokens; no fix-ups.

## 3. Cache layout (real API)

```bash
PageIndex/.venv/bin/python index_examples.py --prompt-layout cache --force
```

Expected: `by_template` shows `cached_tokens` > 0 for most templates, one `outline_whole` call, a
single `placement_check` template instead of two checks; trees validate against the shared schema.

## 4. Decide (real API, costs tokens)

```bash
PageIndex/.venv/bin/python compare_layouts.py --doc DC_COL_10
PageIndex/.venv/bin/python compare_layouts.py --doc all --skip-index
```

Expected: `Output/comparison/layouts_DC_COL_10.md` lists cost, time, tokens by type, sections found,
start-page agreement and golden score per layout and format, with per-question judge reasons and a
`win` / `no win` verdict per the rule in [contracts/harness-cli.md](contracts/harness-cli.md).
