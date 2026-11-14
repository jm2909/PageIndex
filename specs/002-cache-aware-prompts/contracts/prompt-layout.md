# Contract: Cache-aware prompt layout

## Transport (`pageindex/utils.py`)

```python
def llm_completion(model, prompt, chat_history=None, return_finish_reason=False,
                   layout_blocks=None)
async def llm_acompletion(model, prompt, layout_blocks=None, **params)
```

- `layout_blocks=None` (the current layout): behaviour and request bytes unchanged.
- `layout_blocks=LayoutBlocks(system=str, document=str | None, question=str,
  cache_document=bool)`: `prompt` is ignored and the request is

```jsonc
[
  {"role": "system", "content": [{"type": "text", "text": system,
                                  "cache_control": {"type": "ephemeral"}}]},
  {"role": "user", "content": [
     {"type": "text", "text": document, "cache_control": {"type": "ephemeral"}},  // when document
     {"type": "text", "text": question}
  ]}
]
```

- `chat_history` (continuation of a cut-off reply) is appended after these two messages, so the
  cached prefix is unchanged.

## Layout module (`pageindex/cache_layout.py`, new)

```python
SYSTEM_BLOCK: str                        # shared instructions, >= 512 tokens (tested)
def whole_document_block(page_list, start_index=1) -> str      # built once per run, cached
def page_block(page_text) -> str
def question(task: str, **fields) -> str                       # task in TASKS
TASKS = ("toc_detector", "toc_extraction", "outline_whole", "placement_check",
         "toc_index_fixer", "add_page_number", "leaf_summary", "parent_summary",
         "doc_description")
async def warm_then_gather(coros)        # await first, then gather rest; first's failure doesn't stop the rest
```

Reply formats in the cache layout are the current ones, except `placement_check`:

```json
{"thinking": "...", "appears": "yes|no", "starts_at_top": "yes|no"}
```

## Pipeline dispatch (`pageindex/page_index_classic.py`, `pageindex/utils.py`)

With `opt.prompt_layout == "cache"` (format-agnostic; Constitution III):

| Step | Current call | Cache-layout call |
| --- | --- | --- |
| TOC page detection | `toc_detector_single_page` | same step, `toc_detector` question on page block |
| Outline (no TOC) | `generate_toc_init` + `generate_toc_continue` | `outline_whole` on whole-document block if it fits, else current |
| Verify | `check_title_appearance` | `placement_check` (memo filled) |
| Start check | `check_title_appearance_in_start` | memo read; `placement_check` on miss |
| Fix-up | `single_toc_item_index_fixer` (page span) | `toc_index_fixer` on whole-document block, question names pages a–b |
| Summaries | `SummaryScheduler` leaf/parent prompts | same scheduler, `leaf_summary` / `parent_summary` questions |
| Description | `generate_doc_description` | `doc_description` on whole-document block + tree JSON in question |

Every call sets its template name with `llm_template(name)` in both layouts.

## Usage

`usage_by_template` as in [data-model.md](../data-model.md): a top-level key of
`submit_document`'s result, present after every run in both layouts; `usage` itself is unchanged.
