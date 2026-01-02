# Implement Event Hierarchy & Improved Deduplication

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds. This document must be maintained in accordance with `_docs/PLANS.md`.


## Purpose / Big Picture

Currently, nsyc-fetch extracts lottery events (ticket application periods) and concert events as independent, unrelated items. A user cannot answer "what's the next action deadline for this concert?" because there's no link between a lottery and its parent concert. Additionally, re-running extraction often creates near-duplicate events because the current signature `(artist|title|date)` is too sensitive to time precision differences (e.g., `2026-03-01T00:00:00` vs `2026-03-01T17:00:00`).

After this change, users will be able to:
1. See which ticket phases (lotteries, sales) belong to which concert via the `parent_event_id` field
2. Query "what's the next action deadline for concert X?" by filtering events with matching `parent_event_id`
3. Re-run extraction without creating duplicates, as events are matched by stable `event_id` instead of fragile signatures

To verify the change works: run `uv run nsyc-fetch --force`, then inspect `events.json` to confirm events have `event_id` fields, and lottery/sale events have `parent_event_id` pointing to their parent concert's `event_id`.


## Progress

- [x] (2026-01-03) Milestone 1: Update Event model with new fields (event_id, parent_event_id added)
- [x] (2026-01-03) Milestone 2: Update extraction prompt with EVENT ID FORMAT and PARENT-CHILD RELATIONSHIPS sections
- [x] (2026-01-03) Milestone 3: Update event parsing in extract_events() and extract_events_from_section()
- [x] (2026-01-03) Milestone 4: Update save_events() to use event_id for deduplication (removed signature-based matching)
- [x] (2026-01-03) Milestone 5: Add get_ticket_phases() and get_next_action() query utilities
- [ ] Milestone 6: End-to-end validation


## Surprises & Discoveries

(None yet - to be updated during implementation)


## Decision Log

- Decision: Use LLM-generated event_id rather than computing it post-extraction
  Rationale: The LLM has full context about the event (title normalization, which date to use for concerts vs lotteries). Post-extraction computation would require duplicating this logic and could diverge from LLM decisions.
  Date/Author: 2026-01-02 / Initial plan

- Decision: Discard existing events.json and state.json, no migration needed
  Rationale: The existing data is small and can be regenerated. This eliminates the need for a migration script and signature-based fallback logic, significantly simplifying the implementation.
  Date/Author: 2026-01-02 / User decision


## Outcomes & Retrospective

(To be completed at the end of implementation)


## Context and Orientation

This section describes the current state of the codebase relevant to this task.

**What is nsyc-fetch?** A tool that monitors artist websites, extracts time-bound events (concerts, ticket lotteries, sales deadlines) into structured JSON. It uses an LLM (GPT-4o-mini) to parse Japanese entertainment content.

**Key files and their roles:**

- `src/nsyc_fetch/models.py` — Pydantic data models. The `Event` class defines all fields an event can have. Now includes `event_id` and `parent_event_id` fields.

- `src/nsyc_fetch/extractor.py` — Contains `EXTRACTION_PROMPT` (the prompt sent to the LLM) and functions to parse LLM responses into `Event` objects. The prompt currently asks for event_type, title, date, etc., but not event_id or parent references.

- `src/nsyc_fetch/main.py` — Orchestration logic. Contains `save_events()` which merges new events with existing ones using `event_signature()` — a function that creates a string `{artist}|{title}|{date}` for matching.

- `events.json` — Output file containing extracted events (will be regenerated from scratch).

- `state.json` — Tracks which pages have been fetched and their content hashes (will be regenerated from scratch).

**Key terms:**

- **event_id**: A stable, normalized identifier for an event. Format: `lowercase-title-words-YYYY-MM-DD`. Example: `mygo-9th-live-2026-07-18`. Used as the primary key for deduplication.

- **parent_event_id**: For ticket phases (lottery/sale events), this references the parent concert's event_id. Example: a lottery for MyGO 9th LIVE would have `parent_event_id: "mygo-9th-live-2026-07-18"`.

- **Lottery (先行抽選)**: A ticket application period where users apply and are randomly selected. Multiple lottery phases exist for Japanese concerts (CD先行, FC先行, プレイガイド先行, etc.).


## Plan of Work

The implementation proceeds in six milestones, each independently verifiable.


### Milestone 1: Update Event Model (COMPLETED)

Goal: Add `event_id` and `parent_event_id` fields to the Event model so they can be stored and serialized.

Edit `src/nsyc_fetch/models.py`:
- Add `event_id: str | None = Field(default=None, ...)` after the class docstring, before `artist`
- Add `parent_event_id: str | None = Field(default=None, ...)` after `event_id`

After this milestone: The Event model accepts the new fields. Existing code continues to work because fields default to None.


### Milestone 2: Update Extraction Prompt

Goal: Modify the LLM prompt so it generates event_id and parent_event_id for each event.

Edit `src/nsyc_fetch/extractor.py`:
- Update `EXTRACTION_PROMPT` to include event_id and parent_event_id in the field list
- Add a new section explaining event_id format and generation rules
- Add a new section explaining parent-child relationships with examples
- Update the example JSON responses to include the new fields

Key prompt additions:
1. Event ID format: `lowercase-title-words-YYYY-MM-DD` using the EVENT date (concert date), not lottery period dates
2. For lottery/sale events, append phase suffix: `-lottery-cd`, `-lottery-fc`, `-lottery-playguide`, `-sale-general`
3. Parent references: lottery/sale events must set `parent_event_id` to the parent concert's `event_id`

After this milestone: Running extraction will return events with event_id and parent_event_id in the LLM response (though parsing won't use them yet).


### Milestone 3: Update Event Parsing

Goal: Parse the new fields from LLM responses into Event objects.

Edit `src/nsyc_fetch/extractor.py`:
- In `extract_events()`, add `event_id=e.get("event_id")` and `parent_event_id=e.get("parent_event_id")` to the Event constructor
- In `extract_events_from_section()`, add the same two lines to the Event constructor

After this milestone: Extracted Event objects will have event_id and parent_event_id populated from LLM responses.


### Milestone 4: Update save_events() for event_id Deduplication

Goal: Use event_id as the primary deduplication key.

Edit `src/nsyc_fetch/main.py`:
- Modify `save_events()` to build a map `existing_by_id` keyed by event_id
- When upserting a new event:
  - If it has event_id and a match exists in `existing_by_id`, update that event
  - If it has event_id but no match, add it to `existing_by_id`
- Remove the old signature-based matching (no longer needed since we're starting fresh)

After this milestone: Events are deduplicated by event_id.


### Milestone 5: Add Query Utilities

Goal: Provide helper functions to query events by parent-child relationships.

Edit `src/nsyc_fetch/main.py` (or create a new `src/nsyc_fetch/queries.py`):
- Add `get_next_action(concert_id: str, events: list[dict]) -> dict | None` — returns the next active ticket phase for a concert
- Add `get_ticket_phases(concert_id: str, events: list[dict]) -> list[dict]` — returns all ticket phases for a concert

After this milestone: Downstream code can query "what's the next deadline for concert X?"


### Milestone 6: End-to-End Validation

Goal: Verify the entire flow works correctly.

Steps:
1. Delete existing events.json and state.json (fresh start)
2. Run `uv run nsyc-fetch` to extract all events
3. Inspect events.json to verify:
   - All events have event_id
   - Lottery/sale events have parent_event_id pointing to concerts
   - No duplicate events were created
4. Run `uv run nsyc-fetch` again to verify no duplicates are created
5. Run a query utility to find next action for a concert

After this milestone: The feature is complete and verified.


## Concrete Steps

Commands are run from the repository root (`/Users/ghensk/Developer/nsyc-fetch`).

**Milestone 1 verification:**

    uv run python -c "from nsyc_fetch.models import Event; print(Event.model_fields.keys())"

Expected output includes `event_id` and `parent_event_id` in the field list.

**Milestone 2-3 verification:**

    rm -f events.json state.json
    uv run nsyc-fetch

Inspect `events.json` — events should have `event_id` and lottery/sale events should have `parent_event_id`.

**Milestone 6 verification:**

    uv run python -c "
    import json
    with open('events.json') as f:
        events = json.load(f)
    concerts = [e for e in events if e.get('event_type') == 'live']
    for c in concerts[:2]:
        phases = [e for e in events if e.get('parent_event_id') == c.get('event_id')]
        print(f\"{c.get('title')}: {len(phases)} ticket phases\")
    "

Expected output: concert titles with their number of linked ticket phases.


## Validation and Acceptance

The implementation is complete when:

1. **Model fields exist**: `Event.model_fields` includes `event_id` and `parent_event_id`

2. **LLM generates IDs**: After running extraction, events.json contains events with non-null `event_id` values

3. **Parent-child links work**: Lottery/sale events have `parent_event_id` matching a concert's `event_id`

4. **No duplicates on re-run**: Running `uv run nsyc-fetch` twice in succession does not increase the event count (events are updated, not duplicated)

5. **Query utilities work**: `get_next_action()` returns the correct upcoming ticket phase for a given concert


## Idempotence and Recovery

All steps are safe to repeat:

- Model changes are additive (new optional fields with defaults)
- Prompt changes don't affect existing events.json
- save_events() performs upsert by event_id, so re-running updates existing events

If extraction fails partway through:
- State is only updated after successful extraction (existing behavior)
- Re-running will retry failed pages


## Artifacts and Notes

**Event ID format examples:**

    Title: "MyGO!!!!! 9th LIVE"
    Date: 2026-07-18
    event_id: "mygo-9th-live-2026-07-18"

    Title: "MyGO!!!!! 9th LIVE 最速先行抽選" (lottery)
    Parent concert date: 2026-07-18
    event_id: "mygo-9th-live-2026-07-18-lottery-cd"
    parent_event_id: "mygo-9th-live-2026-07-18"

**Deduplication:**

Events are matched solely by event_id. If two events have the same event_id, the newer extraction updates the existing event.


## Interfaces and Dependencies

**New fields in `src/nsyc_fetch/models.py` Event class:**

    event_id: str | None = Field(
        default=None,
        description="Stable identifier for this event. Format: {normalized_title}-{date}. "
                    "Used for deduplication and parent references."
    )

    parent_event_id: str | None = Field(
        default=None,
        description="For ticket phases (lottery/sale), references the parent concert's event_id. "
                    "None for standalone events like concerts or releases."
    )

**Updated function signature in `src/nsyc_fetch/main.py`:**

    def save_events(events: list[Event], events_path: str = "events.json") -> None:
        """Save events using event_id as primary key."""

**New functions (location TBD - main.py or queries.py):**

    def get_next_action(concert_id: str, events: list[dict], now: datetime = None) -> dict | None:
        """Get the next active ticket phase for a concert."""

    def get_ticket_phases(concert_id: str, events: list[dict]) -> list[dict]:
        """Get all ticket phases for a concert, sorted by date."""


---
**Change Log:**
- 2026-01-02: Removed Milestone 5 (migration script) per user decision to discard existing events.json/state.json. Removed signature-based fallback from Milestone 4. Simplified deduplication to use event_id only. Renumbered milestones 6→5, 7→6.
