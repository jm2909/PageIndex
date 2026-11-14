# Feature Specification: Cache-Aware Prompt Layout for Indexing

**Feature Branch**: `feature/cache-aware-prompts` (from Phase 1 commit `2ba037f`)

**Created**: 2026-11-14

**Status**: Draft

## Clarifications

### Session 2026-11-14

- Q: How should golden-set answers be graded? → A: LLM judge against the golden answer and
  evidence excerpt (correct / partly / wrong), verdicts saved for spot checks.
- Q: How big a quality drop still counts as a win? → A: Up to 5% of the maximum score (1.5 points
  on 30 questions) overall; per document (10 questions), at most 1 point lower (refined after the
  spec/plan analysis: 5% of 10 questions would allow almost no variation).
- Q: Which documents does Phase 2 measure on, now that `golden_qa_30.csv` was replaced? → A: The
  three 10-page agreements of the new golden set (Data Center Colocation `DC_COL_10`, Diagnostic
  Laboratory Services `LAB_SVC_10`, Solar Microgrid Operations `SOLAR_OM_10`), PDF in
  `PageIndex/examples/new_test_pdf/`, Markdown in `PageIndex/examples/markdown/`; 10 questions
  each, all `fact_extraction`. The office/warehouse/airport leases are no longer in the golden set.
- Q: Where is Phase 2 token usage recorded? → A: `Token_usage/v2/` for every Phase 2 run, both
  layouts (each row records its `prompt_layout`); `Token_usage/v1/` keeps the Phase 1 runs.

**Input**: User description: "Phase 2: Cache-aware prompt layout for indexing. Restructure the
standard-mode indexing prompts (shared by PDF and Markdown) so that prompt caching can work,
without turning indexing into one long conversation. Every LLM call stays independent, laid out as
a shared cached instruction block, a cached document block at the right scope, and a short uncached
question. Whole-document scope for large-span calls (outline drafting, fix-up, description);
page scope for small per-page calls. Merge the two per-section page checks. Warm the cache before
each parallel step. Opt-in, off by default (Constitution Principle I amendment). Identical prompts
for PDF and Markdown (Principle III). Record token usage per prompt template and compare cost, time
and answer quality against the 30-question golden set before calling it a win. Out of scope:
changing models, Flash mode, the chat/retrieval side, and one growing conversation."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - See where indexing tokens go (Priority: P1)

A developer indexes a document and gets, alongside the usual totals, a breakdown of the LLM work
by prompt template: how many calls each template made and how many input, output, cache-write and
cache-read tokens each used. The breakdown works with the current prompt layout as well as the new
one.

**Why this priority**: Every later decision (which steps to restructure, whether the new layout
paid off) depends on knowing where the tokens go. It is useful on its own even if the new layout
is never adopted.

**Independent Test**: Index a document with the current layout and the LLM mocked; check that the
per-template breakdown is returned (and saved by the harness), that its call counts match the calls made, and that its token
sums equal the run's totals.

**Acceptance Scenarios**:

1. **Given** any document indexed in standard mode, **When** indexing finishes, **Then** a
   per-template usage record is saved next to the run's existing token-usage record.
2. **Given** a per-template record, **When** its numbers are summed, **Then** they equal the run's
   total input, output, cache-write and cache-read tokens.
3. **Given** a run in which a step was retried or repeated (for example the fix-up rounds), **When**
   the record is read, **Then** those calls are counted under their own template, not hidden.

---

### User Story 2 - Index with the cache-aware layout (Priority: P1)

A developer turns on the cache-aware layout and indexes a PDF or Markdown document. Each LLM call is
still an independent request, so calls still run in parallel, but every call begins with the same
shared instruction block, and the calls that read large parts of the document share one cached copy
of it. Repeated content is billed at the cache-read rate instead of in full.

**Why this priority**: This is the feature itself: lower input cost with no loss of parallelism.
The baseline measurement (current layout, the three example pairs) shows the two per-section
placement checks take 72% (PDF) and 82% (Markdown) of input tokens, so merging them and caching the
page text they repeat is where most of the saving lies; fix-up rounds matter on large documents.

**Independent Test**: Index an example pair with the layout on (LLM mocked, cache behaviour
simulated) and check that every call follows the three-part layout, that each step's first call
runs before its parallel calls, and that the per-template record shows cache reads.

**Acceptance Scenarios**:

1. **Given** the layout is on, **When** any indexing call is made, **Then** it starts with the
   shared instruction block, followed by its document content, followed by a short task-specific
   question, and contains no earlier call's question or answer.
2. **Given** the layout is on, **When** an outline-drafting, fix-up or document-description call is
   made, **Then** its document content is the whole document with page markers, identical byte for
   byte across those calls.
3. **Given** the layout is on, **When** a table-of-contents check, section-on-page check or leaf
   summary is made, **Then** its document content is only the relevant page(s), not the whole
   document.
4. **Given** the layout is on, **When** a section's placement is checked, **Then** one call answers
   both "does the section appear on this page" and "does it start at the top of this page".
5. **Given** a step that makes many parallel calls sharing a cached block, **When** the step runs,
   **Then** one call completes first, and the remaining calls start only afterwards.
6. **Given** a PDF and a Markdown document with the same pages, **When** both are indexed with the
   layout on, **Then** they go through the same sequence of prompt templates.

---

### User Story 3 - Decide on evidence whether the new layout wins (Priority: P2)

A developer runs the same documents with both layouts and gets a side-by-side report: cost, time,
tree quality, and answer quality on the 30-question golden set. The new layout is called a win only
if it is cheaper or faster without a quality loss.

**Why this priority**: The layout changes every prompt the indexer sends; a cost saving that costs
answer quality is not a win. This guards the decision, but depends on Stories 1 and 2.

**Independent Test**: Run the comparison on one document pair and check that the report contains
both layouts' numbers for every metric and a stated verdict.

**Acceptance Scenarios**:

1. **Given** a document indexed with both layouts, **When** the comparison runs, **Then** the
   report shows, per layout, total cost, indexing time, tokens by type, sections found and
   section start-page agreement with the reference tree.
2. **Given** both indexes, **When** the golden-set questions for that document are answered from
   each, **Then** the report shows how many answers are correct under each layout.
3. **Given** the results, **When** the verdict is computed, **Then** it says "win" only if cost or
   time improved and answer quality did not fall below the agreed threshold.

---

### User Story 4 - Current behaviour unchanged by default (Priority: P1)

Users who do not turn the layout on get exactly the prompts, calls and trees they get today, for
PDF in both modes and for Markdown.

**Why this priority**: The constitution requires upstream PDF behaviour by default; the layout must
be strictly opt-in.

**Independent Test**: Run the full existing test suite and the PDF baseline comparison with the
layout off.

**Acceptance Scenarios**:

1. **Given** the layout setting is absent or off, **When** a PDF is indexed, **Then** prompts and
   output match the recorded baseline exactly (apart from fields already allowed).
2. **Given** the layout is off, **When** Markdown is indexed, **Then** it uses the Phase 1 prompts
   unchanged.

---

### Edge Cases

- Document too large to fit, as a whole, in one call's context: whole-document calls fall back to
  the current chunked behaviour for that document, and the run says so.
- Shared instruction block or document block shorter than the model's minimum cacheable size:
  calls still work; the per-template record shows no cache reads for them instead of failing.
- Cache entry expires mid-run (a long pause, or a step longer than the cache lifetime): calls still
  succeed and are billed in full; the record shows cache writes where reads were expected.
- The first ("warming") call of a step fails: the step still runs its calls; it does not hang or
  skip them.
- A provider that does not support explicit caching: the layout still produces correct trees; the
  record shows zero cache activity.
- A reply that cannot be parsed (as seen in the Phase 1 office-lease run): behaviour is the same as
  today's for that call type; this feature does not change retry policy.
- Flash mode requested with the layout on: Flash is unaffected; the setting applies to standard
  mode only.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST record, for every standard-mode indexing run, the number of LLM calls and
  the input, output, cache-write and cache-read tokens per prompt template, under both layouts. The
  record is also returned next to the run's token usage, as a separate `usage_by_template` field;
  the usage itself keeps its existing shape (owner's decision, 2026-11-14).
- **FR-002**: System MUST save the per-template record alongside the run's existing token-usage
  record (`Token_usage/v2/` for the Phase 2 harness runs, both layouts) and the per-template sums
  MUST equal the run's totals.
- **FR-003**: System MUST provide a cache-aware layout setting, off by default, that applies to
  standard-mode indexing of both PDF and Markdown and has no effect on Flash mode.
- **FR-004**: With the layout on, every indexing call MUST be an independent request made of three
  parts in this order: a shared instruction block (identical for every call of the run), the
  call's document content, and a short task-specific question. No call may contain another call's
  question or answer.
- **FR-005**: The shared instruction block MUST cover every indexing task's instructions and MUST
  be long enough to meet the configured model's minimum cacheable size on its own.
- **FR-006**: With the layout on, outline drafting, the fix-up step, the document description and
  (for documents with a printed table of contents that lacks page numbers) the step that finds each
  listed section's page MUST use the whole document with page markers as their document content,
  identical byte for byte across those calls within a run.
- **FR-007**: With the layout on, table-of-contents detection, the steps that read and convert a
  printed table of contents, section placement checks and leaf summaries MUST use only their own
  page(s) as document content.
- **FR-008**: With the layout on, the two per-section placement checks ("appears on page",
  "starts at top of page") MUST be answered by one call per section.
- **FR-009**: With the layout on, outline drafting MUST read the whole document in one call when
  it fits the model's context, and MUST fall back to the current chunked drafting otherwise.
- **FR-010**: With the layout on, each step that makes parallel calls sharing a cached block MUST
  complete one call before starting the rest, and MUST still run the rest if that call fails.
- **FR-011**: With the layout on, the content intended for caching MUST be marked for caching in a
  way the configured provider understands; providers without explicit caching MUST still work.
- **FR-012**: Under either layout, PDF and Markdown inputs with the same pages MUST go through the
  same sequence of prompt templates (Constitution Principle III).
- **FR-013**: With the layout off, indexing MUST be unchanged: same prompts, calls and output as
  today for PDF (both modes) and Markdown.
- **FR-014**: System MUST provide a comparison that indexes a document under both layouts and
  reports cost, time, tokens by type, sections found, section start-page agreement and golden-set
  answer correctness for each, with a verdict.
- **FR-015**: The verdict MUST be "win" only when cost or indexing time improves and golden-set
  answer correctness does not drop below the threshold in FR-016.
- **FR-016**: Golden-set answer correctness MUST be judged by an LLM judge that compares each answer
  with the golden set's `expected_answer`, given its `supporting_clauses` (clause names) and source
  page/section as context, and marks it correct (1 point), partly correct (0.5) or wrong (0). If a
  future golden set marks a question as not answerable from the document, saying so counts as
  correct. The judge's verdict and reason are saved per question so a developer can spot-check
  them. Overall, the new layout MUST NOT score more than 5% of the maximum
  score below the current layout (1.5 points on 30 questions); per document (10 questions each),
  it MUST NOT score more than 1 point below.
- **FR-018**: Both layouts' golden-set answers MUST be produced with the same chat model and chat
  settings (by default the indexing model from the harness `.env`), and the report MUST record
  them, so that only the indexing layout differs between the two runs.
- **FR-017**: The cache-aware layout, and the additional per-template usage field (FR-001), MUST be
  allowed by an explicit constitution amendment (Principle I) before they are merged, recorded with
  a Sync Impact Report and version bump.

### Key Entities

- **Prompt template**: a named kind of indexing call (for example table-of-contents detection,
  outline drafting, section placement check, fix-up, leaf summary, document description).
- **Per-template usage record**: for one run, per template: calls, input, output, cache-write and
  cache-read tokens; plus run identity (document, format, layout, model, time).
- **Layout**: the setting choosing between the current prompts and the cache-aware layout.
- **Shared instruction block**: the instructions common to every call in a cache-aware run.
- **Document block**: the document content of a call, at whole-document or page scope.
- **Layout comparison report**: both layouts' metrics for one document and the verdict.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For 100% of standard-mode runs, per-template token sums equal the run totals.
- **SC-002**: With the layout on, indexing the three example Markdown files costs at least 40% less
  input-token spend in total (counting cache reads and writes at their prices) than the current
  layout's measured baseline (465,569 input tokens, $0.0466 of input on Claude Haiku 5.5; recorded
  in `Token_usage/v2/`). The same figure is reported for the three PDFs (baseline 256,656 input
  tokens, $0.0257).
  This is the target the comparison report states as met or missed; the win/no-win verdict itself
  follows FR-015 and FR-016.
- **SC-003**: With the layout on, total indexing time for each test document is no more than 10%
  longer than with the current layout (parallelism is kept).
- **SC-004**: With the layout on, at least half of all input tokens across a document's run are
  served as cache reads.
- **SC-005**: Golden-set answer correctness with the layout on is within the FR-016 threshold of the
  current layout for each of the three test documents.
- **SC-006**: Section start-page agreement with the reference (PDF current-layout) tree is no worse
  with the layout on than with it off.
- **SC-007**: With the layout off, 100% of existing tests pass and the PDF baseline matches exactly.
- **SC-008**: Every functional requirement has at least one automated test that runs without network
  access or API keys; the golden-set comparison itself is a separate, explicitly-run measurement.

## Assumptions

- The test model is Claude Haiku 5.5 via the existing LLM access layer; its minimum cacheable
  prefix is 512 tokens, cache writes cost about 1.25× and reads about 0.1× the input price, with a
  5-minute default cache lifetime. Indexing one test document takes about 1–2 minutes, so the
  default lifetime is enough.
- "Reference tree" for start-page agreement is the PDF tree indexed with the current layout; the
  three test documents are the 10-page agreements in `PageIndex/examples/` described by
  `golden_qa_30.csv` (columns `document_id`, `document_pdf`, `document_markdown`, `question`,
  `expected_answer`, `source_pdf_pages`, `source_markdown_section`, `supporting_clauses`,
  `difficulty`, `answer_type`).
- Baseline (current layout, 2026-11-14, `Token_usage/v2/`): per 10-page document about 85K input
  tokens for PDF and 152–159K for Markdown, total cost $0.0632 (3 PDFs) and $0.0887 (3 Markdown
  files); no fix-up rounds occurred on these documents. The 100-page office lease (Phase 1) showed
  fix-up rounds and remains a useful large-document check outside the golden set.
- Answering golden-set questions uses the existing local chat unchanged; improving chat is out of
  scope.
- Running the golden-set comparison spends real API tokens and is run explicitly by the developer,
  never as part of the automated test suite.
- The Phase 1 parse-failure issue (a dropped outline chunk) is not fixed here; a single
  whole-document outline call may reduce it, which the comparison will show.
- Out of scope: changing models, Flash mode, the chat/retrieval side, and a single growing
  conversation (rejected: loses parallelism, grows quadratically, leaks earlier answers into later
  checks).
