# Improve Event Extraction Accuracy via Logging and Prompt Enhancement

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds. This document must be maintained in accordance with `_docs/PLANS.md`.


## Purpose / Big Picture

NSYC-Fetch extracts event information from Japanese artist websites, but currently misses critical details about ticket lottery prerequisites. For example, when a concert requires purchasing a CD to obtain a lottery serial code (known as "CD先行"), the system extracts the deadline correctly but describes the action as "Purchase tickets" instead of "Apply for lottery using CD serial code from 8th Single."

After this work is complete:

1. Developers can inspect exactly what content was sent to the LLM and what response came back, making debugging extraction issues straightforward.
2. The LLM will correctly identify and describe CD先行 patterns, extracting prerequisite information (which CD to buy, what type of application).
3. For sources with many detail pages, per-event extraction will prevent context dilution where critical info from one event gets lost among content from other events.

To verify success, run `uv run nsyc-fetch --force` and check that MyGO!!!!! 9th LIVE has `action_description` mentioning "8th Single" or "CD" or "シリアル", and a separate lottery event is created.


## Progress

- [x] (2026-01-02 00:09Z) Milestone 1: Implement structured logging infrastructure
  - Created `src/nsyc_fetch/logger.py` with global singleton `RunLogger`
  - Integrated into `main.py` (init_logger/close_logger) and `extractor.py`
  - Logs saved to `logs/{timestamp}/{source_id}/` with fetched_content.json, llm_request.json, llm_response.json, extracted_events.json
  - Verified: All CD先行 info (申込券, シリアル, 8th Single, 静降想) captured in logs
- [x] (2026-01-02 12:30Z) Milestone 2: Improve extraction prompt for CD先行 pattern
  - Updated `EXTRACTION_PROMPT` with explicit CD先行/シリアル先行 pattern guidance
  - Added プレイガイド先行 (playguide priority) pattern
  - Added CRITICAL instruction to create SEPARATE lottery events (not mix with live events)
  - Fixed EventType parsing to map invalid types to "other"
  - Results: 3 lottery events correctly extracted with specific CD/product requirements
    - MyGO 9th LIVE: "Apply using serial code from 8th Single (first-press)"
    - Ave Mujica TOUR: "Apply for lottery using serial code from Ave Mujica 3rd Single (first-press)"
    - ツーマンライブ: "Apply for tickets through playguide (2 tickets per person)"
  - All 5 live events now have action_required=false (lottery info on separate events)
- [ ] Milestone 3: Implement per-event extraction option


## Surprises & Discoveries

- Observation: The fetcher correctly captures all CD先行 information (申込券, シリアル, 8th Single, 静降想).
  Evidence: Running `extract_detail_page_content()` on `https://bang-dream.com/events/mygo_9th` returns 897 chars containing all key terms.

- Observation: Content is not being truncated before the critical info.
  Evidence: Combined content is 12,263 chars; truncation at 12,000 chars only cuts 263 chars from the end (Section 7, mygo-avemujica2026), while mygo_9th info is in Section 5.

- Observation: The root cause is prompt-level, not fetcher-level.
  Evidence: All key terms (最速先行抽選, 申込券, シリアル, 8th Single) are present in the content sent to the LLM, but output still says "Purchase tickets" instead of describing the lottery application with CD serial.


## Decision Log

- Decision: Implement logging before prompt improvement.
  Rationale: Logging infrastructure enables systematic debugging of future extraction issues. Without it, we would repeat manual verification steps for each new problem.
  Date/Author: 2026-01-01

- Decision: Store logs as JSON files in a `logs/` directory rather than a database.
  Rationale: JSON files are human-readable, easy to grep, and require no additional dependencies. The volume is low (one log per source per run).
  Date/Author: 2026-01-01

- Decision: Implement per-event extraction as an optional mode rather than replacing batch extraction.
  Rationale: Per-event extraction increases API costs (multiple LLM calls vs one). Users should choose based on their cost/accuracy tradeoff preferences.
  Date/Author: 2026-01-01

- Decision: Use global singleton pattern for logger instead of parameter passing.
  Rationale: Passing logger through every function is verbose and hard to maintain. Global singleton with `init_logger()`, `get_logger()`, `close_logger()` is cleaner and matches Python's built-in logging pattern.
  Date/Author: 2026-01-02


## Outcomes & Retrospective

(To be filled after implementation)


## Context and Orientation

NSYC-Fetch is a Python CLI tool that monitors Japanese artist websites and extracts time-bound events into structured JSON. The codebase lives in `src/nsyc_fetch/` with four main modules:

- `main.py` — CLI entry point, orchestrates the fetch-extract-save pipeline
- `fetcher.py` — HTTP requests using httpx, HTML parsing with BeautifulSoup, link extraction
- `extractor.py` — LLM prompt construction, OpenAI API calls, JSON response parsing
- `models.py` — Pydantic schemas for Event, EventType, SourceContent, FetchState

Key data flow:

1. `main.py` reads `sources.yaml` and iterates over each source
2. `fetcher.py:fetch_source()` fetches listing page, extracts links, fetches detail pages
3. Content hash compared against `state.json` to skip unchanged sources
4. `extractor.py:extract_events()` sends content to GPT-4o-mini with a prompt
5. Events saved to `events.json`

The problem: The extraction prompt in `extractor.py` (lines 11-57) mentions lottery patterns but does not explain the "CD先行" pattern where lottery application requires purchasing a CD that contains a serial code. The LLM sees text like "MyGO!!!!! 8th Single「静降想」初回生産分に封入の申込券でご応募いただけます" but outputs "Purchase tickets" instead of extracting the prerequisite.


## Plan of Work

### Milestone 1: Implement Structured Logging Infrastructure

Create a logging system that captures fetcher output and LLM interactions in a traceable, structured format.

**New file: `src/nsyc_fetch/logger.py`**

This module provides a `RunLogger` class that:
- Creates a timestamped log directory for each run (e.g., `logs/2026-01-01T22-30-00/`)
- Saves fetched content for each source as JSON
- Saves LLM request/response pairs as JSON
- Provides a summary of the run

**Modifications to `src/nsyc_fetch/main.py`**

- Import and instantiate `RunLogger` at the start of the run
- Pass logger to `fetch_artist_events()` and related functions
- Call logger methods after fetching and extraction

**Modifications to `src/nsyc_fetch/extractor.py`**

- Add optional `logger` parameter to `extract_events()`
- Log the prompt sent and response received

**Log structure:**

    logs/
      2026-01-01T22-30-00/
        run_summary.json          # Overall run metadata
        bangdream-events-mygo/
          fetched_content.json    # Raw sections, combined content
          llm_request.json        # Prompt sent to LLM
          llm_response.json       # Raw LLM response
          extracted_events.json   # Parsed events

### Milestone 2: Improve Extraction Prompt for CD先行 Pattern

Enhance the `EXTRACTION_PROMPT` in `extractor.py` to explicitly teach the LLM about CD先行 patterns.

**Key additions to the prompt:**

1. Explain CD先行/シリアル先行 pattern: lottery requires purchasing a CD/DVD/Blu-ray that contains a serial code (申込券/シリアル)
2. Instruct to extract prerequisites in `action_description`
3. Instruct to create separate events for lottery application periods
4. Provide example of correct extraction for CD先行 pattern

**Example prompt addition:**

    IMPORTANT PATTERN - CD先行 / シリアル先行 (CD Priority Lottery):
    When you see patterns like:
    - "○○に封入の申込券でご応募" (apply using voucher included in ○○)
    - "シリアルコードでご応募" (apply using serial code)
    - "初回生産分" or "初回限定盤" (first-press or limited edition)

    This means the lottery REQUIRES purchasing a specific product first.
    Extract this as:
    - event_type: "lottery"
    - action_description: Include the prerequisite, e.g., "Apply for lottery using serial code from [Product Name] (first-press edition)"
    - The deadline shown is for lottery APPLICATION, not ticket purchase

### Milestone 3: Implement Per-Event Extraction Option

Add an option to extract events from each detail page separately rather than combining all content.

**Modifications to `sources.yaml` schema:**

Add optional `extraction_mode` field to source configuration:
- `batch` (default): Combine all sections and extract in one LLM call
- `per_page`: Send each detail page to LLM separately

**Modifications to `src/nsyc_fetch/main.py`:**

- Read `extraction_mode` from source config
- When `per_page`, call `extract_events()` for each detail page content separately
- Merge results and deduplicate

**Benefits:**
- Each LLM call has focused context (one event's details)
- No risk of context dilution or truncation cutting relevant info
- Easier to debug which page produced which events

**Tradeoffs:**
- More API calls = higher cost (roughly 10x for 10 detail pages)
- Slightly slower due to sequential API calls


## Concrete Steps

### Milestone 1: Logging Infrastructure

**Step 1.1: Create logger module**

Create file `src/nsyc_fetch/logger.py` with the `RunLogger` class. The class should:
- Initialize with a base logs directory (default: `logs/`)
- Create a timestamped subdirectory for the current run
- Provide methods: `log_fetch()`, `log_llm_request()`, `log_llm_response()`, `log_events()`, `write_summary()`

**Step 1.2: Integrate logger into main.py**

In `src/nsyc_fetch/main.py`:
- Import `RunLogger` from `.logger`
- In `main()` function, create logger instance before processing sources
- Pass logger to `fetch_artist_events()`
- After each source is processed, call appropriate log methods

**Step 1.3: Add logging to extractor.py**

In `src/nsyc_fetch/extractor.py`:
- Add optional `logger` parameter to `extract_events()` function signature
- Before calling OpenAI API, log the full prompt via `logger.log_llm_request()`
- After receiving response, log via `logger.log_llm_response()`

**Step 1.4: Verify logging works**

Run:

    uv run nsyc-fetch --force

Check that `logs/` directory is created with the expected structure. Verify:
- `run_summary.json` exists and contains run metadata
- Each source has a subdirectory with `fetched_content.json`, `llm_request.json`, `llm_response.json`
- Content is human-readable JSON

### Milestone 2: Prompt Improvement

**Step 2.1: Update EXTRACTION_PROMPT**

In `src/nsyc_fetch/extractor.py`, modify the `EXTRACTION_PROMPT` string (lines 11-57) to add:
- Explicit section about CD先行/シリアル先行 pattern recognition
- Instructions to extract prerequisite information
- Example of correct extraction

**Step 2.2: Verify improved extraction**

Run:

    uv run nsyc-fetch --force

Check `events.json` for MyGO!!!!! 9th LIVE entry. Expected improvements:
- `event_type` should include a separate "lottery" event for the 最速先行抽選
- `action_description` should mention "8th Single" or "静降想" or "シリアル" or "申込券"

Also check logs to compare before/after LLM responses.

### Milestone 3: Per-Event Extraction

**Step 3.1: Update models.py**

Add `extraction_mode` field to source configuration model (if exists) or handle as optional string.

**Step 3.2: Update main.py**

In `fetch_artist_events()`:
- Read `extraction_mode` from source config (default: "batch")
- If "per_page", iterate over detail page contents and call `extract_events()` for each
- Collect all events and deduplicate

**Step 3.3: Update sources.yaml**

Add example configuration showing both modes.

**Step 3.4: Verify per-event extraction**

Modify `sources.yaml` to set `extraction_mode: per_page` for one source. Run:

    uv run nsyc-fetch --force

Verify:
- Logs show separate LLM calls per detail page
- Events are correctly extracted and merged
- No duplicate events in output


## Validation and Acceptance

### Milestone 1 Acceptance

After completing Milestone 1, running `uv run nsyc-fetch --force` should:

1. Create a `logs/` directory with timestamped subdirectory
2. For each source (e.g., `bangdream-events-mygo`), create:
   - `fetched_content.json` containing the sections sent to LLM
   - `llm_request.json` containing the full prompt
   - `llm_response.json` containing the raw LLM response
   - `extracted_events.json` containing parsed events
3. Create `run_summary.json` with metadata (start time, end time, sources processed, events extracted)

To verify manually:

    ls logs/
    # Should show timestamped directory like 2026-01-01T22-30-00

    cat logs/*/run_summary.json | python -m json.tool
    # Should show valid JSON with run metadata

    cat logs/*/bangdream-events-mygo/llm_request.json | python -m json.tool
    # Should show the prompt with content

### Milestone 2 Acceptance

After completing Milestone 2, running `uv run nsyc-fetch --force` should produce `events.json` where the MyGO!!!!! 9th LIVE related entries:

1. Include a "lottery" type event for the 最速先行抽選 application period
2. Have `action_description` that mentions the CD prerequisite (any of: "8th Single", "静降想", "シリアル", "申込券", "CD")

To verify:

    cat events.json | python -c "
    import json, sys
    events = json.load(sys.stdin)
    mygo_9th = [e for e in events if '9th LIVE' in e.get('title', '')]
    for e in mygo_9th:
        print(f\"Type: {e['event_type']}\")
        print(f\"Action: {e.get('action_description')}\")
        print()
    "

Expected: At least one event with type "lottery" and action_description mentioning the CD.

### Milestone 3 Acceptance

After completing Milestone 3, with `extraction_mode: per_page` configured:

1. Logs should show separate `llm_request.json` files per detail page
2. Events should be correctly extracted from each page
3. No duplicate events in final `events.json`

To verify:

    # Count LLM calls in logs
    ls logs/*/bangdream-events-mygo/page_*/llm_request.json | wc -l
    # Should match number of detail pages fetched


## Idempotence and Recovery

All steps are idempotent:
- Running `uv run nsyc-fetch --force` multiple times creates new log directories (timestamped) without overwriting previous logs
- Code changes are additive; existing functionality preserved
- If a step fails, re-running from that step is safe

To clean up logs:

    rm -rf logs/

To reset to pre-implementation state:

    git checkout src/nsyc_fetch/


## Artifacts and Notes

**Current extraction output for MyGO!!!!! 9th LIVE (problematic):**

    {
      "artist": "MyGO!!!!!",
      "event_type": "live",
      "title": "MyGO!!!!! 9th LIVE",
      "date": "2026-07-18T00:00:00",
      "action_required": true,
      "action_deadline": "2026-02-02T23:59:00",
      "action_description": "Purchase tickets"  // WRONG - should mention CD lottery
    }

**Source content that IS being captured (from verification):**

    最速先行抽選
    受付期間：2025年12月6日(土) 21:00 ～ 2026年2月2日(月) 23:59
    受付はこちら
    ※MyGO!!!!! 8th Single「静降想」初回生産分に封入の申込券でご応募いただけます。
    ※封入のシリアル1枚で、DAY1・DAY2いずれかにご応募いただけます。

**Key terms that survive truncation (verified):**
- mygo_9th: FOUND
- 申込券: FOUND
- シリアル: FOUND
- 8th Single: FOUND
- 静降想: FOUND
- 最速先行抽選: FOUND


## Interfaces and Dependencies

### Milestone 1: Logger Module

In `src/nsyc_fetch/logger.py`, define:

    from datetime import datetime
    from pathlib import Path
    from typing import Any

    class RunLogger:
        def __init__(self, base_dir: str = "logs"):
            """Initialize logger with timestamped run directory."""
            ...

        def log_fetch(self, source_id: str, content: dict[str, Any]) -> None:
            """Log fetched content for a source."""
            ...

        def log_llm_request(self, source_id: str, prompt: str, model: str) -> None:
            """Log the prompt sent to LLM."""
            ...

        def log_llm_response(self, source_id: str, response: str, tokens_used: int | None = None) -> None:
            """Log the raw LLM response."""
            ...

        def log_events(self, source_id: str, events: list[dict]) -> None:
            """Log extracted events."""
            ...

        def write_summary(self, summary: dict[str, Any]) -> None:
            """Write run summary."""
            ...

        @property
        def run_dir(self) -> Path:
            """Return the current run's log directory."""
            ...

### Milestone 2: Prompt Changes

No new interfaces. Modify existing `EXTRACTION_PROMPT` constant in `src/nsyc_fetch/extractor.py`.

### Milestone 3: Per-Event Extraction

In `src/nsyc_fetch/main.py`, modify `fetch_artist_events()` to accept and use `extraction_mode` parameter:

    async def fetch_artist_events(
        artist_config: dict,
        state: FetchState,
        client: OpenAI,
        force: bool = False,
        logger: RunLogger | None = None,
    ) -> list[Event]:
        ...
        # For each source, check extraction_mode
        extraction_mode = source.get("extraction_mode", "batch")
        if extraction_mode == "per_page":
            # Extract from each detail page separately
            ...
        else:
            # Current batch behavior
            ...
