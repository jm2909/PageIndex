# Contract: Harness and CLI

## Library / CLI setting

| Surface | Form |
| --- | --- |
| `config.yaml` | `prompt_layout: "standard"` |
| `run_pageindex.py` | `--prompt-layout {standard,cache}`; error with `--mode flash`: "--prompt-layout applies to standard mode only" |
| `PageIndexLocalClient(..., index={..., "prompt_layout": "cache"})` | passed to `LocalAPI` and into `opt` |
| `page_index(doc, ..., prompt_layout=None)` | `None` keeps the config value |

## `index_documents.py` (harness, repo root of the workspace)

New flag `--prompt-layout {standard,cache}` (default `standard`). Stores are per layout:
`Output/<format>_based/store` (standard, unchanged path) and `Output/<format>_based/store_cache`
(cache). Token-usage JSON/CSV gain `prompt_layout`, `by_template`, `cost_usd`.

## `compare_layouts.py` (harness, new)

```
PageIndex/.venv/bin/python compare_layouts.py --doc {DC_COL_10,LAB_SVC_10,SOLAR_OM_10,all} [--formats pdf,markdown]
        [--judge-model MODEL] [--chat-model MODEL] [--skip-index] [--questions N]
```

Steps per document × format: index with both layouts (or reuse with `--skip-index`), answer the
document's golden questions from each index with the local chat, grade with the judge, write
`Output/comparison/layouts_<doc>.md` and `.json`, print the verdict. Spends real API tokens; never
run by the test suite.

Judge reply (JSON): `{"verdict": "correct|partly|wrong", "reason": "..."}`; an unparseable reply
is retried once, then recorded as `wrong` with reason `"unparseable judge reply"`.

Verdict rule: `win` when (cost lower OR time lower) AND overall
`score_cache >= score_standard - 0.05 * max_score` (1.5 on 30) AND for every document
`score_cache >= score_standard - 1`. The report also states whether the SC-002 target (≥ 40% lower
input spend on the three example Markdown files vs the baseline) was met; that target is not part of the verdict.

Both layouts' answers use the same chat model and chat settings (`--chat-model`, default the
`.env` model); the report records them (FR-018).
