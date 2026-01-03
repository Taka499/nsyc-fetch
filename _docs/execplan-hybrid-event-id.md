# Implement Hybrid Event ID with Two-Dimensional Ticket Model

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds. This document must be maintained in accordance with `_docs/PLANS.md`.


## Purpose / Big Picture

Currently, the LLM generates both `event_id` and `parent_event_id` directly, causing inconsistency: the same concert extracted twice may get different IDs, lottery events may reference non-existent parent IDs, and deduplication fails when IDs don't match exactly.

Additionally, the current model conflates two orthogonal dimensions of ticket information: what you need to participate (CD, FC membership, playguide) and which round in the sequence (fastest, secondary, general).

After this change, users will see:

1. Stable, deterministic event IDs that remain consistent across extractions (e.g., `mygo-9th-live-2026-07-18` for a concert, `mygo-9th-live-2026-07-18-lottery-cd-fastest` for its CD lottery).
2. Correct parent-child relationships where lottery/sale events properly reference their parent concert.
3. Rich ticket metadata showing both the requirement (cd, fc, playguide, none) and priority (fastest, secondary, general) as separate fields.
4. Specific product details for CD requirements (e.g., "8th Single「静降想」初回限定盤").

To verify success, run `uv run nsyc-fetch --force` and examine `events.json`. Each event should have a deterministic `event_id`, lottery/sale events should have valid `parent_event_id` references to their parent concerts, and ticket phases should have `ticket_requirement`, `ticket_priority`, and optionally `ticket_requirement_detail` fields populated.


## Progress

- [x] Milestone 1: Update models.py with new enums and fields
- [x] Milestone 2: Add generate_event_id() utility function
- [x] Milestone 3: Update extraction prompt in extractor.py
- [x] Milestone 4: Add post-extraction processing
- [x] Milestone 5: Add cross-page parent resolution in main.py
- [x] Milestone 6: Integration testing and validation


## Surprises & Discoveries

- One `ticket_priority` warning for "プレイガイド先行" which was classified as `other` - this is expected since playguide lotteries often don't follow the fastest/secondary/tertiary pattern


## Decision Log

- Decision: Skip migration script
  Rationale: User confirmed `events.json` can be removed without cost, so no need for backwards-compatible migration.
  Date/Author: 2026-01-03


## Outcomes & Retrospective

**Completed: 2026-01-03**

**What went well:**
- All 6 milestones completed successfully
- Validation passed with no missing event_ids, orphan parent references, or missing ticket fields
- 17 events extracted with proper parent-child relationships
- Lottery events correctly reference their parent concerts
- Ticket requirement details populated with specific product names (e.g., `8th Single「静降想」初回限定盤`)

**Validation results:**
```
Total events: 17
Validation complete
```
(No MISSING or ORPHAN messages)

**Sample event_id formats working correctly:**
- Concert: `mygo-9th-live-2026-07-18`
- CD最速先行: `mygo-9th-live-2026-07-18-lottery-cd-fastest`
- プレイガイド先行: `mygoave-mujica-ツーマンライブ-moment-memory-2026-03-01-lottery-playguide-other`


## Context and Orientation

This repository (nsyc-fetch) monitors official artist websites and extracts time-bound events (concerts, ticket lotteries, sales deadlines) into structured JSON. The core flow is: `sources.yaml` (configuration) → Webpage scraping → LLM extraction (GPT-4o-mini) → `events.json` (output).

Key files involved in this change:

- `src/nsyc_fetch/models.py`: Pydantic data models including `Event`, `EventType`, and state classes. This is where we add new enums and fields.
- `src/nsyc_fetch/extractor.py`: Contains `EXTRACTION_PROMPT` (the LLM prompt) and extraction functions. This is where we update the prompt and add post-processing.
- `src/nsyc_fetch/main.py`: Orchestration logic. This is where we add cross-page parent resolution.

Key terms:

- **event_id**: A stable identifier for an event, computed deterministically from title + date + ticket fields. Format: `normalized-title-YYYY-MM-DD` for concerts, with suffix `-{event_type}-{requirement}-{priority}` for lottery/sale.
- **parent_event_id**: For lottery/sale events, references the parent concert's event_id. Enables hierarchical event relationships.
- **parent_title**: LLM-provided field containing the exact title of the parent concert. Used by code to resolve parent_event_id.
- **ticket_requirement**: What you need to participate in a lottery/sale: `cd` (serial code from CD/Blu-ray), `fc` (fan club membership), `playguide` (ticket vendor), `none` (general public), `other`.
- **ticket_priority**: Which round in the ticket sequence: `fastest` (最速先行), `secondary` (2次先行), `tertiary` (3次先行), `general` (一般発売), `other`.
- **ticket_requirement_detail**: For CD requirements, the specific product name (e.g., "8th Single「静降想」初回限定盤").


## Plan of Work

The implementation proceeds in six milestones, each building on the previous. Each milestone is independently verifiable.


### Milestone 1: Update models.py with new enums and fields

Add `TicketRequirement` and `TicketPriority` enums to model the two-dimensional ticket information. Add new fields to the `Event` class: `parent_title`, `ticket_requirement`, `ticket_priority`, and `ticket_requirement_detail`.

In `src/nsyc_fetch/models.py`, after the `EventType` enum (around line 17), add two new enums:

    class TicketRequirement(str, Enum):
        """What you need to participate in the lottery/sale."""
        CD = "cd"              # Requires CD/Blu-ray serial code purchase
        FC = "fc"              # Requires fan club membership
        PLAYGUIDE = "playguide"  # Through ticket vendor (e+, Lawson, etc.)
        NONE = "none"          # No special requirement (general public)
        OTHER = "other"        # Doesn't fit above categories


    class TicketPriority(str, Enum):
        """Which round/priority level in the ticket sale sequence."""
        FASTEST = "fastest"      # 最速先行, 1次先行
        SECONDARY = "secondary"  # 2次先行
        TERTIARY = "tertiary"    # 3次先行
        GENERAL = "general"      # 一般発売
        OTHER = "other"          # Doesn't fit pattern

In the `Event` class, add new fields after `parent_event_id`:

    # LLM provides this for parent resolution
    parent_title: str | None = Field(
        default=None,
        description="For lottery/sale events, the exact title of the parent concert.",
    )

    # Ticket phase fields (LLM provides for lottery/sale)
    ticket_requirement: TicketRequirement | None = Field(
        default=None,
        description="What you need to participate: cd, fc, playguide, none, other.",
    )
    ticket_priority: TicketPriority | None = Field(
        default=None,
        description="Which round: fastest, secondary, tertiary, general, other.",
    )
    ticket_requirement_detail: str | None = Field(
        default=None,
        description="For CD requirement, the specific product name. "
        "E.g., '8th Single「静降想」初回限定盤'",
    )

Verification: Run `uv run python -c "from nsyc_fetch.models import Event, TicketRequirement, TicketPriority; print('OK')"`. Should print "OK" without errors.


### Milestone 2: Add generate_event_id() utility function

Add a function to `models.py` that generates stable, deterministic event IDs from title, date, and optional ticket fields.

At the top of `src/nsyc_fetch/models.py`, add `import re` to the imports.

After the `Event` class, add:

    def generate_event_id(
        title: str,
        date: datetime,
        event_type: str | None = None,
        ticket_requirement: str | None = None,
        ticket_priority: str | None = None,
    ) -> str:
        """Generate a stable, deterministic event ID.

        Args:
            title: Event title (e.g., "MyGO!!!!! 9th LIVE")
            date: Event date
            event_type: For lottery/sale, adds to suffix
            ticket_requirement: For lottery/sale, adds to suffix (cd, fc, playguide, none)
            ticket_priority: For lottery/sale, adds to suffix (fastest, secondary, etc.)

        Returns:
            Normalized ID like:
            - "mygo-9th-live-2026-07-18" (concert)
            - "mygo-9th-live-2026-07-18-lottery-cd-fastest" (CD最速先行)
        """
        # Normalize title
        normalized = title.lower()

        # Remove common lottery/sale suffixes from title
        lottery_patterns = [
            r"最速先行.*$",
            r"[1-9]次先行.*$",
            r"cd先行.*$",
            r"シリアル先行.*$",
            r"fc先行.*$",
            r"ファンクラブ先行.*$",
            r"プレイガイド先行.*$",
            r"一般発売.*$",
            r"先行抽選.*$",
            r"抽選.*$",
        ]
        for pattern in lottery_patterns:
            normalized = re.sub(pattern, "", normalized, flags=re.IGNORECASE)

        # Replace Japanese brackets with hyphens
        normalized = normalized.replace("「", "-").replace("」", "-")

        # Remove special characters except hyphens and alphanumeric
        normalized = re.sub(r"[^\w\s\-]", "", normalized)

        # Collapse whitespace to single hyphen
        normalized = re.sub(r"\s+", "-", normalized.strip())

        # Remove consecutive hyphens
        normalized = re.sub(r"-+", "-", normalized)

        # Strip leading/trailing hyphens
        normalized = normalized.strip("-")

        # Add date
        date_str = date.strftime("%Y-%m-%d")
        event_id = f"{normalized}-{date_str}"

        # Add suffix for lottery/sale events
        if event_type in ("lottery", "sale"):
            requirement = ticket_requirement or "other"
            priority = ticket_priority or "other"
            event_id = f"{event_id}-{event_type}-{requirement}-{priority}"

        return event_id

Verification: Run the following test:

    uv run python -c "
    from datetime import datetime
    from nsyc_fetch.models import generate_event_id

    # Test basic concert
    assert generate_event_id('MyGO!!!!! 9th LIVE', datetime(2026, 7, 18)) == 'mygo-9th-live-2026-07-18'

    # Test lottery with CD requirement
    result = generate_event_id(
        'MyGO!!!!! 9th LIVE',
        datetime(2026, 7, 18),
        event_type='lottery',
        ticket_requirement='cd',
        ticket_priority='fastest'
    )
    assert result == 'mygo-9th-live-2026-07-18-lottery-cd-fastest', f'Got: {result}'

    print('All tests passed!')
    "


### Milestone 3: Update extraction prompt in extractor.py

Replace the `EXTRACTION_PROMPT` constant in `src/nsyc_fetch/extractor.py` with a new prompt that:
1. Asks the LLM to provide `parent_title` instead of generating `parent_event_id`
2. Asks for `ticket_requirement`, `ticket_priority`, and `ticket_requirement_detail`
3. Removes instructions for LLM to generate `event_id` (code will compute it)

Replace the entire `EXTRACTION_PROMPT` (lines 12-153) with:

    EXTRACTION_PROMPT = """You are an event extraction assistant for Japanese entertainment content.
    Given the following content from {source_url}, extract any time-bound events related to the artist "{artist_name}".

    For each event found, extract:
    1. event_type: One of: live, release, lottery, sale, broadcast, streaming, screening, other
    2. title: Event title (in original language)
    3. date: Event date (ISO format: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
    4. end_date: End date if it's a multi-day event or period (optional)
    5. venue: Venue name (optional, for live events)
    6. location: City/area (optional)
    7. action_required: true if user needs to take action
    8. action_deadline: Deadline for action if applicable (ISO format)
    9. action_description: What action is needed - BE SPECIFIC
    10. event_url: URL for event details (optional)
    11. ticket_url: URL for ticket purchase (optional)
    12. parent_title: For lottery/sale events ONLY, exact title of parent concert
    13. ticket_requirement: For lottery/sale ONLY, what you need (see TICKET REQUIREMENT)
    14. ticket_priority: For lottery/sale ONLY, which round (see TICKET PRIORITY)
    15. ticket_requirement_detail: For CD/serial requirement ONLY, the specific product name

    ## PARENT-CHILD RELATIONSHIPS

    Ticket phases (lottery, sale) are CHILDREN of their parent concert.

    For lottery/sale events:
    - Set `parent_title` to the EXACT title of the parent concert
    - The parent concert should be extracted as a separate "live" event

    For concerts, releases, and other standalone events:
    - Set `parent_title`, `ticket_requirement`, `ticket_priority`, `ticket_requirement_detail` to null

    ## TICKET REQUIREMENT (what you need to participate)

    | ticket_requirement | Japanese Terms | Description |
    |--------------------|----------------|-------------|
    | "cd" | CD先行, シリアル先行, BD先行, 封入特典 | Requires purchasing CD/Blu-ray with serial code |
    | "fc" | FC先行, ファンクラブ先行, 会員限定 | Requires fan club membership |
    | "playguide" | プレイガイド先行, e+先行, ローチケ先行 | Through ticket vendors |
    | "none" | 一般発売, 一般販売 | No special requirement |
    | "other" | (anything else) | Doesn't fit above |

    ## TICKET PRIORITY (which round in the sequence)

    | ticket_priority | Japanese Terms | Description |
    |-----------------|----------------|-------------|
    | "fastest" | 最速先行, 1次先行, 最速抽選 | First/fastest round |
    | "secondary" | 2次先行, 2次抽選 | Second round |
    | "tertiary" | 3次先行, 3次抽選 | Third round |
    | "general" | 一般発売, 一般販売 | General sale (final) |
    | "other" | (anything else) | Doesn't fit above |

    ## TICKET REQUIREMENT DETAIL

    When ticket_requirement is "cd", extract the SPECIFIC product name:
    - Include the full product title
    - Include edition info (初回限定盤, 通常盤, etc.)
    - This helps users know WHICH product to buy

    Examples:
    - "8th Single「静降想」初回限定盤"
    - "ALBUM「JUNK」初回生産限定盤"
    - "Blu-ray「わかれ道の、その先へ」初回限定盤"

    ## IMPORTANT: MULTIPLE ROUNDS WITH SAME REQUIREMENT

    A concert may have MULTIPLE lotteries requiring different CDs:
    - 最速先行 requiring CD-A
    - 2次先行 requiring CD-B

    Create SEPARATE events for each. The combination of (parent_title + ticket_requirement + ticket_priority + ticket_requirement_detail) should be unique.

    Example for Yonezu Kenshi tour:

    ```json
    {{
      "event_type": "lottery",
      "title": "Yonezu Kenshi TOUR 2026 最速先行",
      "parent_title": "Yonezu Kenshi TOUR 2026",
      "ticket_requirement": "cd",
      "ticket_priority": "fastest",
      "ticket_requirement_detail": "ALBUM「JUNK」初回限定盤",
      "action_description": "Apply using serial code from ALBUM JUNK (first-press edition)"
    }}
    ```

    ```json
    {{
      "event_type": "lottery",
      "title": "Yonezu Kenshi TOUR 2026 2次先行",
      "parent_title": "Yonezu Kenshi TOUR 2026",
      "ticket_requirement": "cd",
      "ticket_priority": "secondary",
      "ticket_requirement_detail": "Single「○○」初回限定盤",
      "action_description": "Apply using serial code from Single ○○ (first-press edition)"
    }}
    ```

    ## CRITICAL RULES

    1. For each concert, create ONE "live" event (parent)
    2. Create SEPARATE "lottery"/"sale" events for EACH ticket phase (children)
    3. Each lottery/sale MUST have:
       - parent_title matching concert's exact title
       - ticket_requirement set
       - ticket_priority set
       - ticket_requirement_detail set (if requirement is "cd")
    4. Lottery date/end_date = APPLICATION PERIOD (not concert date)
    5. action_deadline = when applications close

    Content to analyze:
    ---
    {content}
    ---

    Respond ONLY with a JSON object (no markdown, no explanation):
    {{"events": [
      {{
        "event_type": "live",
        "title": "MyGO!!!!! 9th LIVE",
        "date": "2026-07-18",
        "end_date": "2026-07-19",
        "venue": "ぴあアリーナMM",
        "location": "Yokohama",
        "action_required": false,
        "action_deadline": null,
        "action_description": null,
        "event_url": "https://...",
        "ticket_url": null,
        "parent_title": null,
        "ticket_requirement": null,
        "ticket_priority": null,
        "ticket_requirement_detail": null
      }},
      {{
        "event_type": "lottery",
        "title": "MyGO!!!!! 9th LIVE 最速先行抽選",
        "date": "2025-12-06",
        "end_date": "2026-02-02",
        "venue": null,
        "location": null,
        "action_required": true,
        "action_deadline": "2026-02-02T23:59:00",
        "action_description": "Apply using serial code from 8th Single (first-press edition)",
        "event_url": "https://...",
        "ticket_url": null,
        "parent_title": "MyGO!!!!! 9th LIVE",
        "ticket_requirement": "cd",
        "ticket_priority": "fastest",
        "ticket_requirement_detail": "8th Single「静降想」初回限定盤"
      }}
    ]}}

    If no events are found, respond with: {{"events": []}}
    """

Verification: Run `uv run python -c "from nsyc_fetch.extractor import EXTRACTION_PROMPT; print('Prompt loaded, length:', len(EXTRACTION_PROMPT))"`. Should print the prompt length without errors.


### Milestone 4: Add post-extraction processing

Add a `process_extracted_events()` function to `extractor.py` that generates event_ids and resolves parent references. Update both `extract_events()` and `extract_events_from_section()` to use the new function and parse the new fields.

First, update the imports at the top of `src/nsyc_fetch/extractor.py` to include the new types:

    from .models import (
        Event,
        EventType,
        TicketRequirement,
        TicketPriority,
        generate_event_id,
    )

After the `EXTRACTION_PROMPT` constant, add the `process_extracted_events()` function:

    def process_extracted_events(events: list[Event]) -> list[Event]:
        """Post-process extracted events: generate event_ids and resolve parent references.

        Args:
            events: List of events from LLM

        Returns:
            Events with event_id and parent_event_id populated
        """
        # Step 1: Build lookup of concerts by title
        concerts_by_title: dict[str, Event] = {}
        for event in events:
            if event.event_type == EventType.LIVE:
                concerts_by_title[event.title] = event

        # Step 2: Generate event_id for concerts first
        for event in events:
            if event.event_type == EventType.LIVE:
                event.event_id = generate_event_id(
                    title=event.title,
                    date=event.date,
                )

        # Step 3: Generate event_id for lottery/sale and resolve parent
        for event in events:
            if event.event_type not in (EventType.LOTTERY, EventType.SALE):
                continue

            # Get parent concert
            parent = concerts_by_title.get(event.parent_title) if event.parent_title else None

            # Determine base title and date for ID
            if parent:
                base_title = parent.title
                base_date = parent.date
                event.parent_event_id = parent.event_id
            else:
                base_title = event.title
                base_date = event.date
                event.parent_event_id = None

            # Generate event_id with requirement and priority
            requirement = event.ticket_requirement.value if event.ticket_requirement else "other"
            priority = event.ticket_priority.value if event.ticket_priority else "other"

            event.event_id = generate_event_id(
                title=base_title,
                date=base_date,
                event_type=event.event_type.value,
                ticket_requirement=requirement,
                ticket_priority=priority,
            )

        # Step 4: Generate event_id for remaining events (release, broadcast, etc.)
        for event in events:
            if event.event_id is None:
                event.event_id = generate_event_id(
                    title=event.title,
                    date=event.date,
                )

        # Step 5: Log unknown values for observability
        for event in events:
            if event.event_type in (EventType.LOTTERY, EventType.SALE):
                if event.ticket_requirement == TicketRequirement.OTHER:
                    print(f"  [WARN] Unknown ticket_requirement for: {event.title}")
                if event.ticket_priority == TicketPriority.OTHER:
                    print(f"  [WARN] Unknown ticket_priority for: {event.title}")

        return events

Update the event parsing in `extract_events()` function (around line 257-286). Replace the event parsing block with:

    for e in result.get("events", []):
        try:
            # Handle invalid event types by mapping to "other"
            raw_type = e.get("event_type", "other")
            try:
                event_type = EventType(raw_type)
            except ValueError:
                event_type = EventType.OTHER

            # Parse ticket_requirement
            raw_requirement = e.get("ticket_requirement")
            ticket_requirement = None
            if raw_requirement:
                try:
                    ticket_requirement = TicketRequirement(raw_requirement)
                except ValueError:
                    ticket_requirement = TicketRequirement.OTHER

            # Parse ticket_priority
            raw_priority = e.get("ticket_priority")
            ticket_priority = None
            if raw_priority:
                try:
                    ticket_priority = TicketPriority(raw_priority)
                except ValueError:
                    ticket_priority = TicketPriority.OTHER

            event = Event(
                artist=artist_name,
                event_type=event_type,
                title=e.get("title", "Unknown Event"),
                date=_parse_date(e.get("date")),
                end_date=_parse_date(e.get("end_date")),
                venue=e.get("venue"),
                location=e.get("location"),
                action_required=e.get("action_required", False),
                action_deadline=_parse_date(e.get("action_deadline")),
                action_description=e.get("action_description"),
                event_url=e.get("event_url"),
                ticket_url=e.get("ticket_url"),
                source_url=source_url,
                # Parent resolution fields
                parent_title=e.get("parent_title"),
                # Ticket phase fields
                ticket_requirement=ticket_requirement,
                ticket_priority=ticket_priority,
                ticket_requirement_detail=e.get("ticket_requirement_detail"),
                # Leave for post-processing
                event_id=None,
                parent_event_id=None,
            )
            events.append(event)
        except Exception as parse_err:
            print(f"Warning: Failed to parse event: {parse_err}")
            continue

    # Post-process to generate event_ids and resolve parents
    events = process_extracted_events(events)
    return events

Apply the same changes to `extract_events_from_section()` function (around line 471-502). The event parsing block should be updated similarly, and add the post-processing call before the return.

Verification: Run `uv run python -c "from nsyc_fetch.extractor import process_extracted_events; print('OK')"`. Should print "OK" without errors.


### Milestone 5: Add cross-page parent resolution in main.py

Add a `resolve_cross_page_parents()` function to `main.py` that resolves parent references for events extracted from different pages. Call it after collecting all source events.

Update the imports at the top of `src/nsyc_fetch/main.py`:

    from .models import DetailPageState, Event, EventType, FetchState, generate_event_id

After the `get_next_action()` function (around line 187), add:

    def resolve_cross_page_parents(events: list[Event]) -> list[Event]:
        """Resolve parent references for events extracted from different pages.

        Args:
            events: All events from a single source (may span multiple pages)

        Returns:
            Events with parent_event_id resolved where possible
        """
        # Build lookup of concerts by title
        concerts_by_title: dict[str, Event] = {}
        for event in events:
            if event.event_type == EventType.LIVE:
                concerts_by_title[event.title] = event

        # Resolve any events with parent_title but no parent_event_id
        for event in events:
            if event.parent_title and not event.parent_event_id:
                parent = concerts_by_title.get(event.parent_title)
                if parent:
                    event.parent_event_id = parent.event_id

                    # Regenerate event_id using parent's data
                    if event.event_type in (EventType.LOTTERY, EventType.SALE):
                        requirement = event.ticket_requirement.value if event.ticket_requirement else "other"
                        priority = event.ticket_priority.value if event.ticket_priority else "other"

                        event.event_id = generate_event_id(
                            title=parent.title,
                            date=parent.date,
                            event_type=event.event_type.value,
                            ticket_requirement=requirement,
                            ticket_priority=priority,
                        )

        return events

In the `fetch_artist_events()` function, after `all_events.extend(source_events)` (around line 335), add cross-page resolution for that source:

    # Resolve cross-page parent references within this source
    source_events = resolve_cross_page_parents(source_events)

    print(f"  Extracted {len(source_events)} events from {source_id}")
    all_events.extend(source_events)

Verification: Run `uv run python -c "from nsyc_fetch.main import resolve_cross_page_parents; print('OK')"`. Should print "OK" without errors.


### Milestone 6: Integration testing and validation

Run the full pipeline and verify the output.

First, remove any existing events.json to start fresh:

    rm -f events.json

Run the fetcher with force flag to re-extract all pages:

    uv run nsyc-fetch --force

Examine the output in events.json. For each event, verify:

1. `event_id` is present and follows the format `normalized-title-YYYY-MM-DD` (with `-{type}-{requirement}-{priority}` suffix for lottery/sale)
2. For lottery/sale events: `parent_event_id` references a valid concert's `event_id`
3. For lottery/sale events: `ticket_requirement` is one of: cd, fc, playguide, none, other
4. For lottery/sale events: `ticket_priority` is one of: fastest, secondary, tertiary, general, other
5. For CD requirements: `ticket_requirement_detail` contains the product name

Example validation command:

    uv run python -c "
    import json
    with open('events.json') as f:
        events = json.load(f)

    print(f'Total events: {len(events)}')

    # Check event_ids
    for e in events:
        if not e.get('event_id'):
            print(f'  MISSING event_id: {e[\"title\"]}')

    # Check parent references
    event_ids = {e['event_id'] for e in events if e.get('event_id')}
    for e in events:
        if e.get('parent_event_id') and e['parent_event_id'] not in event_ids:
            print(f'  ORPHAN parent_event_id: {e[\"title\"]} -> {e[\"parent_event_id\"]}')

    # Check ticket fields
    for e in events:
        if e.get('event_type') in ('lottery', 'sale'):
            if not e.get('ticket_requirement'):
                print(f'  MISSING ticket_requirement: {e[\"title\"]}')
            if not e.get('ticket_priority'):
                print(f'  MISSING ticket_priority: {e[\"title\"]}')

    print('Validation complete')
    "


## Concrete Steps

All commands should be run from the repository root: `/Users/ghensk/Developer/nsyc-fetch`

1. Edit `src/nsyc_fetch/models.py` to add enums and fields (Milestone 1)
2. Add `generate_event_id()` function to `src/nsyc_fetch/models.py` (Milestone 2)
3. Replace `EXTRACTION_PROMPT` in `src/nsyc_fetch/extractor.py` (Milestone 3)
4. Add `process_extracted_events()` and update parsing in `src/nsyc_fetch/extractor.py` (Milestone 4)
5. Add `resolve_cross_page_parents()` and update orchestration in `src/nsyc_fetch/main.py` (Milestone 5)
6. Remove `events.json` and run `uv run nsyc-fetch --force` (Milestone 6)


## Validation and Acceptance

The implementation is successful when:

1. Running `uv run nsyc-fetch --force` completes without errors
2. All events in `events.json` have a non-null `event_id`
3. All lottery/sale events have `ticket_requirement` and `ticket_priority` populated
4. All lottery/sale events with `parent_title` have `parent_event_id` pointing to a valid concert
5. Re-running the fetcher produces the same event_ids (deterministic)

Expected test output from Milestone 2:

    All tests passed!

Expected validation output from Milestone 6:

    Total events: <N>
    Validation complete

(No MISSING or ORPHAN messages should appear)


## Idempotence and Recovery

All steps can be repeated safely. The `--force` flag clears state and re-extracts all pages. If a step fails, fix the issue and re-run `uv run nsyc-fetch --force`.

To reset to a clean state:

    rm -f events.json state.json


## Artifacts and Notes

Example event_id formats:

    Concert:        mygo-9th-live-2026-07-18
    CD最速先行:      mygo-9th-live-2026-07-18-lottery-cd-fastest
    CD2次先行:       mygo-9th-live-2026-07-18-lottery-cd-secondary
    FC先行:         mygo-9th-live-2026-07-18-lottery-fc-fastest
    プレイガイド先行: mygo-9th-live-2026-07-18-lottery-playguide-other
    一般発売:        mygo-9th-live-2026-07-18-sale-none-general


## Interfaces and Dependencies

In `src/nsyc_fetch/models.py`, the following must exist after implementation:

    class TicketRequirement(str, Enum):
        CD = "cd"
        FC = "fc"
        PLAYGUIDE = "playguide"
        NONE = "none"
        OTHER = "other"

    class TicketPriority(str, Enum):
        FASTEST = "fastest"
        SECONDARY = "secondary"
        TERTIARY = "tertiary"
        GENERAL = "general"
        OTHER = "other"

    class Event(BaseModel):
        # ... existing fields ...
        parent_title: str | None
        ticket_requirement: TicketRequirement | None
        ticket_priority: TicketPriority | None
        ticket_requirement_detail: str | None

    def generate_event_id(
        title: str,
        date: datetime,
        event_type: str | None = None,
        ticket_requirement: str | None = None,
        ticket_priority: str | None = None,
    ) -> str: ...

In `src/nsyc_fetch/extractor.py`:

    def process_extracted_events(events: list[Event]) -> list[Event]: ...

In `src/nsyc_fetch/main.py`:

    def resolve_cross_page_parents(events: list[Event]) -> list[Event]: ...
