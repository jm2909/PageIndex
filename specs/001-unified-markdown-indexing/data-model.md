# Data Model: Unified Markdown Indexing

## MarkdownPage (new, in-memory)

| Field | Type | Notes |
| --- | --- | --- |
| `page_index` | int | 1-based, consecutive |
| `text` | str | exact slice of the file, line endings included |
| `tokens` | int | `count_tokens(text, model)` |
| `line_start` | int | 1-based, inclusive |
| `line_end` | int | 1-based, inclusive |

Invariants:

- `"".join(p.text for p in pages) == file_text` (byte-for-byte after UTF-8 decode with
  `newline=""`).
- `pages[i].line_end + 1 == pages[i+1].line_start`; `pages[0].line_start == 1`;
  `pages[-1].line_end == total_lines`.
- No boundary between `pages[i]` and `pages[i+1]` lies inside a protected block, except a logged
  oversized-block cut.
- Converted to the pipeline's `page_list` as `[(p.text, p.tokens) for p in pages]`.

## Stored page (`pages.json`, per document)

| Field | PDF | Markdown |
| --- | --- | --- |
| `page_index` | ✓ | ✓ |
| `markdown` | extracted page text (unchanged name) | exact page slice |
| `line_start` | — | ✓ |
| `line_end` | — | ✓ |

## Document meta (`doc.json` / manifest)

Existing fields unchanged, plus:

| Field | Type | Notes |
| --- | --- | --- |
| `source_type` | `"pdf"` \| `"markdown"` | missing on old documents → read as `"pdf"` |
| `pageNum` | int | PDF pages or Markdown pages |
| `mode` | `"flash"` \| `"standard"` | Markdown is always `"standard"` |

## Tree output envelope

```jsonc
{
  "doc_name": "notes.md",
  "source_type": "markdown",          // NEW, always present
  "doc_description": "...",           // optional
  "structure": [TreeNode, ...]
  // flash-only optional keys unchanged: doc_title, toc_source, optimize,
  // has_abstract_or_references_section
}
```

## TreeNode

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `title` | str | yes | |
| `node_id` | str (4 digits) | when `if_add_node_id` | |
| `start_index` | int ≥ 1 | yes | page |
| `end_index` | int ≥ `start_index` | yes | page; parent covers subtree |
| `summary` | str | when summaries on | describes whole subtree |
| `text` | str | when `if_add_node_text` | |
| `key_items` | [str] | flash optimize only | |
| `line_start` | int | Markdown only, optional | first line of the node's first page ∩ heading line |
| `line_end` | int | Markdown only, optional | last line before the next sibling/ancestor's heading, else page end |
| `nodes` | [TreeNode] | when children exist | |

Page line ranges inside the pipeline: `page_index_main` and `tree_parser` receive only
`page_list = [(text, tokens)]`. Line ranges are recomputed from it with `page_line_ranges`
(page *i* starts at 1 + the number of lines in pages 1..i−1), which gives the same values as the
`MarkdownPage` fields because pages are lossless, contiguous slices.

Heading match rule: a node's heading is the first heading line (ATX or setext, outside fences and
front matter, as found by the pager's scanner) on the node's start page whose normalised text
equals the node's normalised title. Normalise = strip `#` markers / setext underline, trailing
`#`s, surrounding whitespace, inline emphasis/code markers (`*`, `_`, `` ` ``), collapse inner
whitespace, case-fold. If no heading matches, the first whole plain line on the start page
(outside fenced code) whose normalised text equals the normalised title is used, because many
documents write section titles as plain lines (added 2026-11-14 after the office-lease run). No
fuzzy matching; still no match → fall back to the page's `line_start`.

Line range derivation: `line_start` = line of the node's heading if found on its start page, else
`line_start` of the start page; `line_end` = (`line_start` of the next node in document order) − 1
when that node starts within this node's page range, else `line_end` of the node's end page.

## TOC hint item (heading hint, in-memory)

| Field | Type | Notes |
| --- | --- | --- |
| `structure` | str | `"1"`, `"1.2"`, ... from heading levels |
| `title` | str | heading text without `#` / underline |
| `physical_index` | int | page containing the heading line |

## Citation (client `get_citations` entry)

Existing fields unchanged, plus for Markdown documents: `line_start`, `line_end` (from the cited
stored page).
