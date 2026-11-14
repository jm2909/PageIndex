# Feature Specification: Unified Markdown Indexing

**Feature Branch**: `feature/unified-tree-schema`

**Created**: 2026-11-14

**Status**: Draft

**Input**: User description: "Requirements.md, Phase 1. PDF and Markdown documents go through the
same indexing path and the same LLM calls. The only difference is where the text comes from: PDF
text is extracted from each page; Markdown is the file's own text, cut into pages by token count
with its formatting kept exactly. Both produce the same tree, are stored the same way and can be
chatted with the same way."

## Clarifications

### Session 2026-11-14

- Q: How big should each Markdown page be? → A: 800 tokens by default, configurable.
- Q: Should the indexer give the LLM the Markdown `#` headings as a hint? → A: Optional flag,
  off by default; with the flag off the path is identical to PDF.
- Q: What should happen to the old LLM-free Markdown indexer? → A: Keep it behind a command-line
  option, with its current output format unchanged.
- Q: Should Markdown text sent to the LLM get the same prompt-injection redaction as PDF text?
  → A: Yes, same as PDF; only the LLM's copy is redacted, stored pages stay exact.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Index a Markdown file into the same tree as a PDF (Priority: P1)

A developer runs the indexer on a Markdown file and gets back a tree of sections in exactly the
same format a PDF produces: sections with titles, ids, page ranges, summaries that cover each
section's sub-sections, and an optional document description. The tree is built by the same
LLM-driven steps that build PDF trees.

**Why this priority**: The single tree format is the foundation; storage, chat and citations all
depend on it. On its own it already removes the need for a separate Markdown tree format.

**Independent Test**: Index a Markdown fixture from the command line (LLM mocked) and validate the
result against the shared tree schema that PDF output also passes.

**Acceptance Scenarios**:

1. **Given** a Markdown file with headings, prose, code, tables and lists, **When** the developer
   indexes it, **Then** the output has the same fields and meanings as a PDF tree, with page
   ranges, subtree summaries and the source marked as Markdown.
2. **Given** the LLM is mocked, **When** a Markdown document and a PDF built with one physical
   page per Markdown page are indexed, **Then** both make the same sequence of prompt-template
   calls, in the same order and the same number of times.
3. **Given** a Markdown file, **When** it is indexed, **Then** each section also reports the
   original file line range it covers.

---

### User Story 2 - Markdown formatting reaches the pipeline exactly as written (Priority: P1)

The developer's Markdown is cut into pages by size, but its text is never converted or cleaned
up: headings, emphasis, links, tables, code, indentation, blank lines and line endings all stay as
they are. Page breaks never land in the middle of a block that must stay together.

**Why this priority**: Markdown's formatting is its meaning. If pages lose or split formatting,
the tree and chat answers become wrong, so this is as critical as Story 1.

**Independent Test**: Split a fixture containing every block type into pages and check that
joining the pages reproduces the file byte for byte and that no break falls inside a protected
block.

**Acceptance Scenarios**:

1. **Given** any Markdown file, **When** it is split into pages, **Then** joining the pages in
   order gives back the original file byte for byte.
2. **Given** a file with fenced code blocks, tables, lists, blockquotes, HTML blocks and front
   matter, **When** it is split, **Then** no page boundary falls inside any of those blocks.
3. **Given** a single block larger than the page size, **When** it is split, **Then** that block
   becomes one larger page instead of being cut, unless it exceeds the maximum section size, in
   which case it is cut between lines and a warning is logged.
4. **Given** a file containing only whitespace, **When** it is indexed, **Then** it is rejected
   with the same "has no content" message used for blank PDFs.

---

### User Story 3 - Submit and chat with a Markdown document (Priority: P2)

A developer submits a Markdown file to the local client, then browses its structure, reads page
content and asks chat questions about it, using the same calls and tools as for a PDF. Answers
cite the page and the original line range.

**Why this priority**: This is the end goal (Markdown can't be chatted with today), but it builds
on Stories 1 and 2.

**Independent Test**: Submit a Markdown fixture locally (LLM mocked), then request its structure,
page content and a chat answer; check each returns the right sections, exact text and a citation.

**Acceptance Scenarios**:

1. **Given** a Markdown file, **When** it is submitted to the local client without a mode,
   **Then** it is indexed with the standard pipeline and a document id is returned.
2. **Given** a submitted Markdown document, **When** the developer requests its structure and the
   content of a page, **Then** the page content is exactly the text the tree was built from.
3. **Given** a submitted Markdown document, **When** a chat question is asked, **Then** the answer
   cites the document, page and line range, e.g. `[notes.md, p. 3, lines 120–164]`.
4. **Given** a Markdown file, **When** it is submitted with Flash mode requested, **Then** it is
   rejected with "Flash mode supports PDF only; Markdown uses standard mode".

---

### User Story 4 - PDF users see no change (Priority: P1)

Existing users indexing PDFs, in standard or Flash mode, get exactly the same trees, prompts and
LLM calls as before, and their previously stored documents keep working.

**Why this priority**: The fork must not regress upstream's proven PDF path (Constitution
Principle I).

**Independent Test**: Run the full existing test suite and compare PDF outputs and prompt
sequences before and after the change.

**Acceptance Scenarios**:

1. **Given** any PDF, **When** it is indexed in either mode, **Then** the tree and the prompts are
   identical to upstream apart from the added source-type field.
2. **Given** a document stored before this change, **When** it is loaded, **Then** it is treated
   as a PDF and behaves as before.

---

### Edge Cases

- Markdown file with no headings at all: the pipeline treats it like a PDF with no table of
  contents and generates structure from the text.
- File with Windows (`\r\n`) or mixed line endings: kept exactly; line numbers still count lines
  correctly.
- Front matter only at the very top of the file counts as front matter; `---` elsewhere is a
  normal line or setext heading underline.
- An unclosed code fence: everything after the opening fence counts as one block (so it is kept
  together, subject to the oversized-block rule).
- File that is not valid UTF-8: rejected with a clear error naming the file and the encoding.
- Unsupported extension (e.g. `.txt`, `.docx`): rejected with a clear error listing the supported
  types.
- Text that contains prompt-injection phrases: the copy sent to the LLM gets the same redaction as
  PDF text; the stored pages are unchanged.
- Markdown file larger than the LLM's context: handled by the same chunking used for long PDFs.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST accept Markdown files (`.md`, `.markdown`) wherever it accepts PDF
  files for local indexing: the command line, the indexing library call and the local client.
- **FR-002**: System MUST provide Markdown counterparts to each existing PDF text helper (whole
  text, title, text of a page range, page count, page list with token counts, document name), with
  the same inputs and outputs, so either format can be used interchangeably.
- **FR-003**: System MUST split Markdown into pages by a configurable token budget (default 800
  tokens), breaking only between whole lines and preferring breaks just before headings, then at
  blank lines.
- **FR-004**: System MUST NOT place a page break inside a fenced code block, table, list,
  blockquote, HTML block or front matter, except for the last-resort cut of a single block larger
  than the maximum section size, which MUST log a warning.
- **FR-005**: System MUST keep Markdown pages as exact slices of the file: no conversion, no
  normalisation, and joining all pages reproduces the file byte for byte.
- **FR-006**: System MUST record each Markdown page's original first and last line numbers.
- **FR-007**: System MUST run Markdown through the same indexing steps, with the same prompts, as
  PDF standard mode. Format-specific behaviour is allowed only where text enters the system.
- **FR-008**: System MUST produce Markdown trees in the same format as PDF trees (titles, ids,
  page ranges, subtree summaries, optional description) and MUST mark every tree's source type.
- **FR-009**: System MUST add each Markdown section's original line range to its tree node as an
  optional field that no consumer requires.
- **FR-010**: The local client MUST store Markdown documents with the same pages the LLM indexed,
  their line ranges, the source type and the page count.
- **FR-011**: Structure, page content, tree, OCR-style views and chat MUST work for stored Markdown
  documents without Markdown-specific logic in the tools.
- **FR-012**: Chat citations for Markdown documents MUST include the page and, where known, the
  original line range.
- **FR-013**: System MUST use the standard pipeline for Markdown when no mode is given, and MUST
  reject Markdown with a clear message when Flash mode is requested.
- **FR-014**: System MUST reject empty or whitespace-only Markdown files with the same message as
  blank PDFs, and reject unsupported file types and non-UTF-8 files with clear errors.
- **FR-015**: System MUST keep PDF indexing (both modes) unchanged in output, prompts and LLM
  calls, apart from the added source-type field, and MUST treat previously stored documents as
  PDFs.
- **FR-016**: The command line MUST accept the same standard-mode options for Markdown as for PDF
  and MUST keep the existing LLM-free heading-based Markdown indexer available as an opt-in
  option, with its current output format unchanged. Its output is not covered by the shared tree
  schema (FR-008) and is not accepted by the local client.
- **FR-017**: System MUST offer an optional heading-hint setting for Markdown, off by default.
  When on, the Markdown headings are given to the indexing steps as the document's table of
  contents, so the existing "document has a table of contents" handling is used. When off
  (default), Markdown indexing is identical to PDF standard mode (FR-007). The setting MUST have
  no effect on PDFs.
- **FR-018**: System MUST apply the same prompt-injection redaction and wrapping to Markdown text
  sent to the LLM as it applies to PDF text. Redaction MUST affect only the LLM's copy; stored
  pages, page content returned to users and citations MUST stay exactly as in the file.

### Key Entities

- **Document**: a file submitted for indexing; has a name, a source type (PDF or Markdown), a page
  count, an optional description and optional user metadata.
- **Page**: an ordered unit of a document's text. For PDF, the text of one physical page; for
  Markdown, an exact slice of the file with its first and last line numbers.
- **Tree node (section)**: a titled part of the document with an id, a page range, an optional
  summary covering its sub-sections, optional child nodes and, for Markdown, an optional line
  range.
- **Citation**: a reference in a chat answer to a document and page, plus a line range for
  Markdown.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of Markdown test files split into pages that join back to the original file
  byte for byte.
- **SC-002**: 0 page breaks fall inside a protected block (code, table, list, blockquote, HTML,
  front matter) across the test fixtures, apart from logged oversized-block cuts.
- **SC-003**: PDF and Markdown outputs both validate against one shared tree schema in 100% of
  tests.
- **SC-004**: With the LLM mocked and the heading hint off, a Markdown input and a page-matched PDF
  (one physical page per Markdown page) make identical ordered prompt-template call sequences,
  repeats included.
- **SC-005**: A developer can go from a Markdown file to a cited chat answer using the same calls
  as for a PDF, with no Markdown-specific steps.
- **SC-006**: 100% of existing upstream tests pass, and PDF outputs and prompts are unchanged apart
  from the source-type field.
- **SC-007**: Every functional requirement above has at least one automated test that runs without
  network access or API keys.
- **SC-008**: With the heading hint on, a Markdown file with headings is indexed with fewer LLM
  calls than with it off, and its tree still validates against the shared schema.

## Assumptions

- Default Markdown page size is 800 tokens, configurable, so existing page-based settings (pages to
  scan for a table of contents, maximum pages and tokens per section, the 20k-token grouping)
  behave as they do for PDFs. Confirmed in clarification.
- By default Markdown goes through the LLM pipeline even though its headings are already marked;
  the heading hint (FR-017) is opt-in. Confirmed in clarification.
- The existing LLM-free heading-based Markdown indexer stays available as an opt-in command-line
  option, is not the default, and keeps its current output format. Confirmed in clarification.
- Markdown indexing needs an API model, like PDF standard mode; Claude Code models remain
  Flash-only and therefore can't index Markdown.
- Out of scope: the cloud API, Flash mode for Markdown, file types other than Markdown, and indexing
  cost work (prompt caching, single-pass summaries), which is planned as a separate feature.
- Detailed technical requirements, code locations and design notes live in `Requirements.md` at
  the repo root and are inputs to planning.
