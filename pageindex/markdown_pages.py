"""Lossless, block-aware Markdown pages for the standard indexing pipeline.

Markdown is cut into pages by token budget so it can go through the same
``page_list = [(text, tokens), ...]`` path as PDF. Pages are exact slices of
the file: ``"".join(p.text for p in pages)`` is the file, byte for byte. A page
break only falls between whole lines, never inside a fenced code block, table,
list, blockquote, HTML block, front matter or setext heading pair, except the
logged last-resort cut of a single block over ``max_block_tokens``.

Line numbers are 1-based and count ``\\r\\n``, ``\\n`` and ``\\r`` endings only,
as an editor does.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from .utils import count_tokens

logger = logging.getLogger(__name__)

BLANK_MESSAGE = "Markdown has no content. The file is blank."


@dataclass(frozen=True)
class MarkdownPage:
    page_index: int      # 1-based
    text: str            # exact slice, line endings kept
    tokens: int
    line_start: int      # 1-based inclusive
    line_end: int        # 1-based inclusive


@dataclass(frozen=True)
class Heading:
    line: int            # 0-based line index
    level: int           # 1..6
    title: str


@dataclass
class Scan:
    blocks: list         # [(kind, first, last)] 0-based inclusive line indices
    headings: list       # [Heading]
    no_break_before: list  # [bool] per line: a page may not start at this line


# ---------------------------------------------------------------- reading ---

def read_markdown(md_path: str) -> str:
    """The file's text exactly: UTF-8, no newline translation."""
    try:
        with open(md_path, "r", encoding="utf-8", newline="") as f:
            return f.read()
    except UnicodeDecodeError as e:
        raise ValueError(
            f"{md_path}: not valid UTF-8 (byte {e.start}: {e.reason}); "
            f"Markdown files must be UTF-8 encoded."
        ) from None


_LINE_RE = re.compile(r"[^\r\n]*(?:\r\n|\n|\r)|[^\r\n]+\Z")


def split_lines(text: str) -> list[str]:
    """Lines with their endings kept; only \\r\\n, \\n and \\r end a line."""
    return _LINE_RE.findall(text)


# --------------------------------------------------------------- scanning ---

_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_ATX = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
_SETEXT_EQ = re.compile(r"^ {0,3}=+[ \t]*$")
_SETEXT_DASH = re.compile(r"^ {0,3}-+[ \t]*$")
_TABLE_DELIM = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
_LIST_ITEM = re.compile(r"^\s{0,3}([-*+]|\d{1,9}[.)])(\s|$)")
_QUOTE = re.compile(r"^\s{0,3}>")
_HTML = re.compile(r"^\s{0,3}<(?!https?:)[A-Za-z!/?]")


def _body(line: str) -> str:
    return line.rstrip("\r\n")


def _blank(line: str) -> bool:
    return not line.strip()


def _indented(line: str) -> bool:
    return line.startswith(("  ", "\t")) and not _blank(line)


def _atx(line: str):
    m = _ATX.match(_body(line))
    if not m:
        return None
    return len(m.group(1)), (m.group(2) or "").strip()


def scan_markdown(lines: list[str]) -> Scan:
    """Protected blocks, headings and break rules for the given lines."""
    n = len(lines)
    blocks = []
    headings = []
    i = 0

    def protect(kind, first, last):
        blocks.append((kind, first, last))

    # front matter: only when line 1 opens it and a matching line closes it
    if n and _body(lines[0]).strip() in ("---", "+++"):
        mark = _body(lines[0]).strip()
        for j in range(1, n):
            if _body(lines[j]).strip() == mark:
                protect("front_matter", 0, j)
                i = j + 1
                break

    while i < n:
        line = lines[i]
        body = _body(line)

        if _blank(line):
            i += 1
            continue

        m = _FENCE_OPEN.match(body)
        if m:
            char, size = m.group(1)[0], len(m.group(1))
            close = re.compile(r"^ {0,3}" + re.escape(char) + "{" + str(size) + r",}[ \t]*$")
            j = i + 1
            while j < n and not close.match(_body(lines[j])):
                j += 1
            last = min(j, n - 1)  # unclosed fence runs to end of file
            protect("fence", i, last)
            i = last + 1
            continue

        atx = _atx(line)
        if atx:
            headings.append(Heading(i, atx[0], atx[1]))
            i += 1
            continue

        nxt = _body(lines[i + 1]) if i + 1 < n else None

        stripped = body.lstrip()
        if stripped.startswith("|") or ("|" in body and nxt is not None and _TABLE_DELIM.match(nxt)):
            j = i
            while j + 1 < n and not _blank(lines[j + 1]) and "|" in lines[j + 1]:
                j += 1
            if j > i:
                protect("table", i, j)
                i = j + 1
                continue

        if _LIST_ITEM.match(body):
            j = i
            while j + 1 < n:
                following = lines[j + 1]
                if _LIST_ITEM.match(_body(following)) or _indented(following):
                    j += 1
                elif (_blank(following) and j + 2 < n
                      and (_LIST_ITEM.match(_body(lines[j + 2])) or _indented(lines[j + 2]))):
                    j += 2
                else:
                    break
            if j > i:
                protect("list", i, j)
            i = j + 1
            continue

        if _QUOTE.match(body):
            j = i
            while j + 1 < n and _QUOTE.match(_body(lines[j + 1])):
                j += 1
            if j > i:
                protect("blockquote", i, j)
            i = j + 1
            continue

        if _HTML.match(body):
            j = i
            while j + 1 < n and not _blank(lines[j + 1]):
                j += 1
            if j > i:
                protect("html", i, j)
            i = j + 1
            continue

        if nxt is not None and (_SETEXT_EQ.match(nxt) or _SETEXT_DASH.match(nxt)):
            level = 1 if _SETEXT_EQ.match(nxt) else 2
            headings.append(Heading(i, level, body.strip()))
            protect("setext", i, i + 1)
            i += 2
            continue

        i += 1

    no_break = [False] * n
    for _, first, last in blocks:
        for k in range(first + 1, last + 1):
            no_break[k] = True
    for k in range(n):
        if _blank(lines[k]):
            no_break[k] = True  # blank lines stay with the text before them
    protected_end = {first: last for _, first, last in blocks}
    for h in headings:
        # a heading stays on the page of the first line that follows it
        k = protected_end.get(h.line, h.line) + 1
        while k < n and _blank(lines[k]):
            k += 1
        if k < n:
            no_break[k] = True
    return Scan(blocks=blocks, headings=headings, no_break_before=no_break)


# ----------------------------------------------------------------- paging ---

def split_markdown_pages(text: str, model: str | None = None,
                         page_tokens: int = 800,
                         max_block_tokens: int = 20000) -> list[MarkdownPage]:
    """Greedy, block-aware, lossless pages of about ``page_tokens`` tokens.

    Callers pass the active ``max_token_num_each_node`` as ``max_block_tokens``:
    a single unbreakable block larger than that is cut between lines, with a
    warning; a smaller block over the budget becomes one larger page.
    """
    if not text.strip():
        raise ValueError(BLANK_MESSAGE)
    lines = split_lines(text)
    scan = scan_markdown(lines)
    heading_starts = {h.line for h in scan.headings}

    # segments: runs of lines between allowed break points
    starts = [0] + [k for k in range(1, len(lines)) if not scan.no_break_before[k]]
    segments = []  # (first_line, last_line)
    for a, b in zip(starts, starts[1:] + [len(lines)]):
        segments.append((a, b - 1))

    def seg_text(seg):
        return "".join(lines[seg[0]:seg[1] + 1])

    def tokens_of(t):
        return count_tokens(t, model=model)

    seg_tokens = [tokens_of(seg_text(s)) for s in segments]

    page_ranges = []  # (first_line, last_line)
    current = []      # segment indices on the open page
    current_tokens = 0

    def close(upto):
        """Close the open page after current[:upto]; return what carries over."""
        nonlocal current, current_tokens
        kept, carried = current[:upto], current[upto:]
        if kept:
            page_ranges.append((segments[kept[0]][0], segments[kept[-1]][1]))
        current = carried
        current_tokens = sum(seg_tokens[s] for s in carried)

    def best_break():
        """How many segments of the open page to keep: prefer a break just
        before a heading, then after a blank line, in the page's second half."""
        running = 0
        heading_at = blank_at = None
        for pos, s in enumerate(current):
            if pos and running >= page_tokens / 2:
                first = segments[s][0]
                if first in heading_starts:
                    heading_at = pos
                elif _blank(lines[first - 1]):
                    blank_at = pos
            running += seg_tokens[s]
        return heading_at or blank_at or len(current)

    for idx, seg in enumerate(segments):
        tok = seg_tokens[idx]
        if tok > max_block_tokens:
            close(len(current))
            for piece in _cut_oversized(lines, seg, page_tokens, tokens_of):
                page_ranges.append(piece)
            logger.warning(
                "Markdown block at lines %d-%d has %d tokens, over the %d-token limit: "
                "oversized block cut between lines.", seg[0] + 1, seg[1] + 1, tok, max_block_tokens)
            continue
        if current and current_tokens + tok > page_tokens:
            close(best_break())
            if current and current_tokens + tok > page_tokens:
                close(len(current))
        current.append(idx)
        current_tokens += tok
    close(len(current))

    pages = []
    for number, (a, b) in enumerate(page_ranges, start=1):
        page_text = "".join(lines[a:b + 1])
        pages.append(MarkdownPage(page_index=number, text=page_text,
                                  tokens=tokens_of(page_text),
                                  line_start=a + 1, line_end=b + 1))
    return pages


def _cut_oversized(lines, seg, page_tokens, tokens_of):
    """Line-boundary pieces of about ``page_tokens`` for one oversized block."""
    pieces = []
    first = seg[0]
    running = 0
    for k in range(seg[0], seg[1] + 1):
        t = tokens_of(lines[k])
        if running and running + t > page_tokens:
            pieces.append((first, k - 1))
            first, running = k, 0
        running += t
    pieces.append((first, seg[1]))
    return pieces


# ------------------------------------------------ page_list based helpers ---
# page_index_main and tree_parser only see page_list = [(text, tokens)], also
# when the local client passes it in, so these work from the page texts alone.

def page_line_ranges(page_list) -> list[tuple[int, int]]:
    """(line_start, line_end) per page, from the page texts alone."""
    ranges = []
    done = 0
    for text, _ in page_list:
        count = len(split_lines(text))
        ranges.append((done + 1, done + count) if count else (done + 1, done + 1))
        done += count
    return ranges


def _headings_by_page(page_list):
    """[(page_number, line_number, level, title)] outside fences/front matter;
    the scan runs over the whole document, so fence state crosses pages."""
    lines = []
    page_of_line = []
    for number, (text, _) in enumerate(page_list, start=1):
        page_lines = split_lines(text)
        lines.extend(page_lines)
        page_of_line.extend([number] * len(page_lines))
    scan = scan_markdown(lines)
    return [(page_of_line[h.line], h.line + 1, h.level, h.title) for h in scan.headings]


def extract_heading_toc(page_list) -> list[dict]:
    """The Markdown headings as a table of contents for the heading hint:
    [{"structure": "1.2", "title": str, "physical_index": int}]."""
    toc = []
    levels = []    # heading levels of the open ancestors
    counters = []  # structure number per depth
    for page, _, level, title in _headings_by_page(page_list):
        if not title:
            continue
        # depth is relative: a heading nests under the nearest shallower one,
        # so skipped levels (# then ###) and a document starting at ## work
        while levels and levels[-1] >= level:
            levels.pop()
        levels.append(level)
        depth = len(levels)
        counters = counters[:depth]
        if len(counters) < depth:
            counters.append(0)
        counters[-1] += 1
        toc.append({"structure": ".".join(str(c) for c in counters),
                    "title": title, "physical_index": page})
    return toc


_INLINE_MARKS = re.compile(r"[*_`]")


def normalise_title(title: str) -> str:
    t = re.sub(r"^\s*#+\s*", "", title or "")
    t = re.sub(r"\s+#+\s*$", "", t)
    t = _INLINE_MARKS.sub("", t)
    return " ".join(t.split()).casefold()


def _plain_title_line(page_text, first_line, wanted):
    """Line number of the first whole line on the page, outside fenced code,
    whose normalised text equals the title: many documents write section
    titles as plain lines rather than Markdown headings."""
    lines = split_lines(page_text)
    fenced = {k for kind, a, b in scan_markdown(lines).blocks if kind == "fence"
              for k in range(a, b + 1)}
    for offset, line in enumerate(lines):
        if offset not in fenced and normalise_title(line) == wanted:
            return first_line + offset
    return None


def _preorder(nodes, out=None):
    out = [] if out is None else out
    for node in nodes:
        start = len(out)
        out.append([node, 0])
        _preorder(node.get("nodes") or [], out)
        out[start][1] = len(out) - start  # subtree size, node included
    return out


def add_markdown_line_ranges(structure, page_list) -> None:
    """Add line_start/line_end to every node in place (data-model.md)."""
    ranges = page_line_ranges(page_list)
    by_page = {}
    for page, line, _, title in _headings_by_page(page_list):
        by_page.setdefault(page, []).append((line, normalise_title(title)))

    order = _preorder(structure)
    for node, _ in order:
        start = node.get("start_index")
        if not start or start > len(ranges):
            continue
        wanted = normalise_title(node.get("title", ""))
        match = next((line for line, t in by_page.get(start, []) if t == wanted), None)
        if match is None and wanted:
            match = _plain_title_line(page_list[start - 1][0], ranges[start - 1][0], wanted)
        node["line_start"] = match if match is not None else ranges[start - 1][0]

    for pos, (node, size) in enumerate(order):
        if "line_start" not in node:
            continue
        end = min(node.get("end_index") or node["start_index"], len(ranges))
        line_end = ranges[end - 1][1]
        if pos + size < len(order):
            nxt = order[pos + size][0]  # next node that is not a descendant
            if "line_start" in nxt and nxt.get("start_index", 0) <= end:
                line_end = max(node["line_start"], nxt["line_start"] - 1)
        node["line_end"] = line_end
