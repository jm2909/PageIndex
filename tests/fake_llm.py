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
]

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


class FakeLLM:
    def __init__(self, verify_answer="yes", verify_no_first=0):
        self.calls = []  # [(template, prompt)]
        self.verify_answer = verify_answer
        self.verify_no_first = verify_no_first  # answer "no" to this many first checks

    @property
    def templates(self):
        return [t for t, _ in self.calls]

    def reply(self, prompt):
        name = template_of(prompt)
        self.calls.append((name, prompt))
        if name == "toc_detector":
            return json.dumps({"thinking": "", "toc_detected": "no"})
        if name == "check_title_appearance":
            if self.verify_no_first > 0:
                self.verify_no_first -= 1
                return json.dumps({"thinking": "", "answer": "no"})
            return json.dumps({"thinking": "", "answer": self.verify_answer})
        if name == "check_title_start":
            return json.dumps({"thinking": "", "start_begin": "yes"})
        if name == "generate_toc_init":
            return json.dumps(_sections(_given_text(prompt)))
        if name == "generate_toc_continue":
            return json.dumps(_sections(_given_text(prompt), skip_first=True))
        if name in ("leaf_summary", "parent_summary"):
            return json.dumps({"summary": f"summary ({name})"})
        return f"description ({name})"

    def completion(self, model, prompt, chat_history=None, return_finish_reason=False, **_):
        text = self.reply(prompt)
        return (text, "finished") if return_finish_reason else text

    async def acompletion(self, model, prompt, **_):
        return self.reply(prompt)

    @contextlib.contextmanager
    def patched(self):
        with patch("pageindex.page_index_classic.llm_completion", self.completion), \
             patch("pageindex.page_index_classic.llm_acompletion", self.acompletion), \
             patch("pageindex.utils.llm_completion", self.completion), \
             patch("pageindex.utils.llm_acompletion", self.acompletion):
            yield self
