# Contract: Markdown pager and helpers

## `pageindex/markdown_pages.py`

```python
@dataclass(frozen=True)
class MarkdownPage:
    page_index: int      # 1-based
    text: str            # exact slice, line endings kept
    tokens: int
    line_start: int      # 1-based inclusive
    line_end: int        # 1-based inclusive

def read_markdown(md_path: str) -> str
    # UTF-8, newline="" (no newline translation).
    # Raises ValueError("<path>: not valid UTF-8 ...") on decode error.

def split_markdown_pages(text: str, model: str | None = None,
                         page_tokens: int = 800,
                         max_block_tokens: int = 20000) -> list[MarkdownPage]
    # max_block_tokens is the last-resort cut threshold. Callers MUST pass the active
    # max_token_num_each_node (Constitution II); 20000 is only the function default and
    # equals config.yaml's default.
    # Raises ValueError("Markdown has no content. The file is blank.") when text.strip() == "".
    # Guarantees the invariants in data-model.md (lossless, contiguous lines,
    # no break inside protected blocks except a logged oversized cut).

def page_line_ranges(page_list: list[tuple[str, int]]) -> list[tuple[int, int]]
    # (line_start, line_end) per page, derived from the page texts alone: pages are exact,
    # contiguous slices, so page i starts at 1 + the line count of all earlier pages
    # (lines counted with split_lines(): only \r\n, \n and \r end a line, as in an editor;
    # str.splitlines() is not used because it also splits on \v, \f, \x1c-\x1e,   ...).
    # Equals the MarkdownPage line ranges for the same pages.

def extract_heading_toc(page_list: list[tuple[str, int]]) -> list[dict]
    # [{"structure": "1.2", "title": str, "physical_index": int}], headings outside
    # code fences and front matter only; the scanner runs over the pages in order and
    # carries fence/front-matter state across page boundaries. Used only when the
    # heading hint is on.

def add_markdown_line_ranges(structure: list[dict], page_list: list[tuple[str, int]]) -> None
    # Adds line_start/line_end to every node in place (data-model "Line range derivation"),
    # using page_line_ranges(page_list).

# These three take the pipeline's own page_list, not MarkdownPage objects, because
# page_index_main and tree_parser only ever see page_list (the local client passes it in
# via page_index_main(..., page_list=...)). No extra parameters or re-reading of the file.
```

## `pageindex/utils.py` counterparts (FR-002)

Each mirrors its PDF twin's arguments and return type; all build on `get_markdown_pages`.

| PDF helper | Markdown helper | Returns |
| --- | --- | --- |
| `extract_text_from_pdf(pdf_path)` | `extract_text_from_markdown(md_path)` | `str`, whole file |
| `get_pdf_title(pdf_path)` | `get_markdown_title(md_path)` | first level-1 heading text, else `'Untitled'` |
| `get_text_of_pages(pdf_path, start, end, tag=True)` | `get_text_of_markdown_pages(md_path, start, end, tag=True)` | `str`, same `<start_index_N>`/`<end_index_N>` tags |
| `get_number_of_pages(pdf_path)` | `get_number_of_markdown_pages(md_path)` | `int` |
| `get_page_tokens(pdf_path, model, pdf_parser)` | `get_markdown_page_tokens(md_path, model)` | `[(text, tokens)]` |
| `get_pdf_name(pdf_path)` | `get_markdown_name(md_path)` | file base name |

Plus:

```python
def is_markdown_path(path) -> bool          # str path ending .md / .markdown (case-insensitive)
def get_markdown_pages(md_path, model=None, page_tokens=None, max_block_tokens=None) -> list[MarkdownPage]
    # None → read md_page_tokens / max_token_num_each_node from config.yaml.
    # page_index_main passes opt.md_page_tokens and opt.max_token_num_each_node, so CLI
    # overrides (--md-page-tokens, --max-tokens-per-node) reach the pager.
def get_markdown_page_tokens(md_path, model=None, page_tokens=None, max_block_tokens=None)
    # [(p.text, p.tokens) for p in get_markdown_pages(...)]
def get_doc_name(doc) -> str                 # markdown → get_markdown_name, else get_pdf_name
```

`get_page_tokens(path, ...)`: if `is_markdown_path(path)` → `get_markdown_page_tokens`; else the
existing PDF code, unchanged.
