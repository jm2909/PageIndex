"""A deterministic, offline stand-in for the indexing LLM.

It recognises each prompt template by a fixed phrase from the template (never
by document content), records the template name and the full prompt, and
returns a plausible reply. Patch it in with ``fake_llm.patched()``.
"""
import contextlib
import json
import re
from unittest.mock import patch

TEMPLATES = [
    ("toc_detector", "detect if there is a table of content"),
    ("check_title_appearance", "check if the given section appears or starts"),
    ("check_title_start", "starts in the beginning of the given page_text"),
    ("generate_toc_init", "generate the tree structure of the document"),
    ("generate_toc_continue", "continue the tree structure from the previous part"),
    ("leaf_summary", "You are given a text chunk from a document."),
    ("parent_summary", "You are given a section of a document: the text that opens"),
    ("node_summary", "generate a description of the partial document"),
    ("doc_description", "generating descriptions for a document"),
    ("toc_index_fixer", "find the physical index of the start page of the section"),
]

# Cache layout: the question block starts with "TASK: <name>" (contracts/prompt-layout.md)
_TASK_LINE = re.compile(r"^TASK:\s*(\w+)", re.M)

_MARKER = re.compile(r"<physical_index_(\d+)>")


def template_of(prompt):
    for name, phrase in TEMPLATES:
        if phrase in prompt:
            return name
    raise AssertionError(f"fake LLM: unknown prompt template: {prompt[:200]!r}")


def _pages_in(text):
    """{page: page text} for a <physical_index_N> ... <physical_index_N> text."""
    pages = {}
    parts = _MARKER.split(text)
    # parts: [pre, n, body, n, between, n, body, n, ...]
    i = 1
    while i + 1 < len(parts):
        n, body = int(parts[i]), parts[i + 1]
        if n not in pages:
            pages[n] = body
            i += 4  # skip the closing marker and the gap after it
        else:
            i += 2
    return pages


def _title_for(body):
    lines = [l.strip() for l in body.splitlines() if l.strip()]
    for line in lines:
        if line.startswith("#"):
            return line.lstrip("#").strip()
    return lines[0][:60] if lines else None


def _sections(text, skip_first=False):
    pages = _pages_in(text)
    keys = sorted(pages)
    if skip_first and keys:
        keys = keys[1:]
    out = []
    for n in keys:
        title = _title_for(pages[n])
        if title:
            out.append({"structure": str(len(out) + 1), "title": title,
                        "physical_index": f"<physical_index_{n}>"})
    return out


def _given_text(prompt):
    body = prompt.split("Given text\n:", 1)[-1]
    return body.split("\nPrevious tree structure", 1)[0]


def _fields(question):
    """`key: value` lines of a cache-layout question block."""
    out = {}
    for line in question.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            out[key.strip().lower()] = value.strip()
    return out


def _tokens(text):
    return max(1, len(text or "") // 4)


class FakeLLM:
    def __init__(self, verify_answer="yes", verify_no_first=0, report_usage=True):
        self.calls = []   # [(template, prompt)]; cache layout: prompt = system+document+question
        self.blocks = []  # cache layout only: [(template, system, document, question)]
        self.events = []  # [("start"|"end", template, call number)] in order
        self.replies = []  # reply text of every call, in call order
        self.verify_answer = verify_answer
        self.verify_no_first = verify_no_first  # answer "no" to this many first checks
        self.report_usage = report_usage
        self._seen = set()  # cached blocks seen in this run (simulated provider cache)

    @property
    def templates(self):
        return [t for t, _ in self.calls]

    def _verify(self):
        if self.verify_no_first > 0:
            self.verify_no_first -= 1
            return "no"
        return self.verify_answer

    def reply(self, prompt):
        name = template_of(prompt)
        self.calls.append((name, prompt))
        if name == "toc_detector":
            return json.dumps({"thinking": "", "toc_detected": "no"})
        if name == "check_title_appearance":
            return json.dumps({"thinking": "", "answer": self._verify()})
        if name == "check_title_start":
            return json.dumps({"thinking": "", "start_begin": "yes"})
        if name == "generate_toc_init":
            return json.dumps(_sections(_given_text(prompt)))
        if name == "generate_toc_continue":
            return json.dumps(_sections(_given_text(prompt), skip_first=True))
        if name == "toc_index_fixer":
            pages = sorted(_pages_in(prompt.split("Document pages:", 1)[-1]))
            return json.dumps({"thinking": "", "physical_index":
                               f"<physical_index_{pages[0]}>" if pages else None})
        if name in ("leaf_summary", "parent_summary"):
            return json.dumps({"summary": f"summary ({name})"})
        return f"description ({name})"

    def reply_layout(self, blocks):
        """Answer a cache-layout call (system, document, question blocks)."""
        question = blocks.question
        m = _TASK_LINE.search(question)
        if not m:
            raise AssertionError(f"fake LLM: cache-layout question without TASK line: {question[:200]!r}")
        name = m.group(1)
        document = blocks.document or ""
        self.blocks.append((name, blocks.system, document, question))
        self.calls.append((name, blocks.system + document + question))
        fields = _fields(question)
        if name == "toc_detector":
            return json.dumps({"thinking": "", "toc_detected": "no"})
        if name == "outline_whole":
            sections = _sections(document)
            if "pages" in fields:  # a sub-range of the whole-document block
                a, b = (int(x) for x in re.split(r"[-–]", fields["pages"]))
                sections = [s for s in sections
                            if a <= int(_MARKER.match(s["physical_index"]).group(1)) <= b]
                for i, s in enumerate(sections):
                    s["structure"] = str(i + 1)
            return json.dumps(sections)
        if name == "placement_check":
            return json.dumps({"thinking": "", "appears": self._verify(), "starts_at_top": "yes"})
        if name in ("toc_index_fixer", "add_page_number"):
            first = int(re.split(r"[-–]", fields.get("pages", "1"))[0] or 1)
            return json.dumps({"thinking": "", "physical_index": f"<physical_index_{first}>"})
        if name in ("leaf_summary", "parent_summary"):
            return json.dumps({"summary": f"summary ({name})"})
        return f"description ({name})"

    def _usage(self, prompt, text, blocks=None):
        """Report simulated usage the way LiteLLM does for Anthropic (T004):
        prompt_tokens includes cache writes and reads."""
        if not self.report_usage:
            return
        from types import SimpleNamespace
        from pageindex.utils import _add_usage
        cached = written = 0
        if blocks is not None:
            prompt = blocks.system + (blocks.document or "") + blocks.question
            cacheable = [blocks.system] + ([blocks.document] if blocks.document and blocks.cache_document else [])
            for block in cacheable:
                if block in self._seen:
                    cached += _tokens(block)
                else:
                    self._seen.add(block)
                    written += _tokens(block)
        usage = SimpleNamespace(
            prompt_tokens=_tokens(prompt), completion_tokens=_tokens(text),
            prompt_tokens_details=SimpleNamespace(cached_tokens=cached, cache_write_tokens=written),
            completion_tokens_details=SimpleNamespace(reasoning_tokens=0))
        _add_usage(SimpleNamespace(usage=usage))

    def _answer(self, prompt, layout_blocks):
        number = len(self.calls)
        self.events.append(("start", None, number))
        text = self.reply_layout(layout_blocks) if layout_blocks is not None else self.reply(prompt)
        self.events[-1] = ("start", self.calls[-1][0], number)
        self.replies.append(text)
        self._usage(prompt, text, layout_blocks)
        return text

    def completion(self, model, prompt, chat_history=None, return_finish_reason=False,
                   layout_blocks=None, **_):
        text = self._answer(prompt, layout_blocks)
        self.events.append(("end", self.calls[-1][0], len(self.calls) - 1))
        return (text, "finished") if return_finish_reason else text

    async def acompletion(self, model, prompt, layout_blocks=None, **_):
        import asyncio
        text = self._answer(prompt, layout_blocks)
        number = len(self.calls) - 1
        await asyncio.sleep(0)  # let other started calls interleave, as real calls do
        self.events.append(("end", self.calls[number][0], number))
        return text

    @contextlib.contextmanager
    def patched(self):
        with patch("pageindex.page_index_classic.llm_completion", self.completion), \
             patch("pageindex.page_index_classic.llm_acompletion", self.acompletion), \
             patch("pageindex.utils.llm_completion", self.completion), \
             patch("pageindex.utils.llm_acompletion", self.acompletion):
            yield self
