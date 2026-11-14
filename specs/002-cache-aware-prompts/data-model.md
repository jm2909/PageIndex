# Data Model: Cache-Aware Prompt Layout for Indexing

## Prompt template names (stable identifiers)

| Name | Layout | Document scope (cache layout) |
| --- | --- | --- |
| `toc_detector` | both | page |
| `toc_extraction` (extract / transform / complete checks, page-number detection) | both | page(s) as today; system block cached |
| `outline_init`, `outline_continue` | standard; cache only as fallback | chunk |
| `outline_whole` | cache | whole document |
| `check_title_appearance`, `check_title_start` | standard | page |
| `placement_check` | cache | page |
| `toc_index_fixer` | both | standard: page span; cache: whole document |
| `add_page_number` (TOC-without-page-numbers path) | both | standard: group; cache: whole document |
| `leaf_summary`, `parent_summary`, `node_summary` | both | page / none |
| `doc_description` | both | standard: tree only; cache: whole document + tree |

Any call without a set name is counted under `other` (so sums still equal totals).

## Per-template usage record (`submit_document(...)["usage_by_template"]`)

Returned next to `usage` (not inside it: `usage` keeps its upstream shape). In-process
callers read it from the `_llm_usage_by_template` context variable.

```jsonc
{
  "placement_check": {"calls": 57, "prompt_tokens": 51804, "completion_tokens": 3100,
                      "cached_tokens": 41200, "cache_write_tokens": 1900},
  "...": {}
}
```

Invariants: for each numeric field, the sum over templates equals the run total in `usage`; `calls`
equals the number of model responses received (retries that got a response count).

## Harness token-usage file (`Token_usage/v2/<format>_based/<doc>_<format>_<ts>.json`)

`<doc>` is the golden set's `document_id` (e.g. `DC_COL_10`). `Token_usage/v1/` holds Phase 1
runs and is no longer written.

Existing fields, plus:

| Field | Notes |
| --- | --- |
| `prompt_layout` | `standard` or `cache` |
| `by_template` | the per-template record above |
| `cost_usd` | computed from LiteLLM's price map (R7) |

`token_usage.csv` gains `prompt_layout` and `cost_usd` columns (appended at the end so older rows
stay readable).

## Layout setting

| Where | Name | Values | Default |
| --- | --- | --- | --- |
| `config.yaml` | `prompt_layout` | `standard`, `cache` | `standard` |
| CLI | `--prompt-layout` | same | unset → config |
| Local client | index option `prompt_layout` | same | config |
| `page_index()` | `prompt_layout=` | same | config |

## Call layout (cache layout)

| Part | Content | Cached | Same across calls |
| --- | --- | --- | --- |
| system | shared instruction block (hardening + all task sections) | yes | every call of the run |
| document | whole-document block or page block (`_secure_doc_text` applied) | yes (whole doc); yes (page, when ≥ minimum) | whole-doc: all whole-doc calls; page: calls on that page |
| question | task number, title, page range, extra data (e.g. tree JSON) | no | — |

## Placement memo

Per run: `{(normalised title, page): {"appears": str, "starts_at_top": str}}`, filled by
`placement_check`, read by the start check; a miss triggers one `placement_check` call.

## Layout comparison report (`Output/comparison/layouts_<doc>.md` + `.json`)

Per document × format × layout: seconds, tokens by type, `cost_usd`, sections found, start-page
agreement with the reference tree, golden score (sum of 1 / 0.5 / 0), per-question verdicts with
the judge's reason; plus the verdict (`win` / `no win`) with the rule's numbers.
