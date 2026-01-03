"""Extract events from content using LLM."""

import json
import os
from datetime import datetime

from openai import OpenAI

from .logger import get_logger
from .models import (
    Event,
    EventType,
    TicketPriority,
    TicketRequirement,
    generate_event_id,
)

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
- "8th Single「静降想」初回生産分"
- "ALBUM「JUNK」初回生産限定盤"
- "Blu-ray「わかれ道の、その先へ」初回生産分"

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
        parent = None
        if event.parent_title:
            parent = concerts_by_title.get(event.parent_title)

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
        requirement = (
            event.ticket_requirement.value if event.ticket_requirement else "other"
        )
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


def create_openai_client() -> OpenAI:
    """Create OpenAI client from environment."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable is required")
    return OpenAI(api_key=api_key)


def extract_events(
    content: str,
    artist_name: str,
    source_url: str,
    client: OpenAI | None = None,
    model: str = "gpt-4o-mini",
    source_id: str | None = None,
) -> list[Event]:
    """Extract events from content using LLM.

    Args:
        content: Text content to analyze
        artist_name: Name of the artist to look for
        source_url: URL where content was fetched from
        client: OpenAI client (created if not provided)
        model: Model to use for extraction
        source_id: Source identifier for logging

    Returns:
        List of extracted Event objects
    """
    if client is None:
        client = create_openai_client()

    logger = get_logger()
    log_id = source_id or "unknown"

    # Truncate content if too long (leave room for prompt)
    max_content_length = 12000
    if len(content) > max_content_length:
        content = content[:max_content_length] + "\n...[truncated]"

    prompt = EXTRACTION_PROMPT.format(
        source_url=source_url,
        artist_name=artist_name,
        content=content,
    )

    # Log LLM request
    if logger:
        logger.log_llm_request(
            source_id=log_id,
            prompt=prompt,
            model=model,
            artist_name=artist_name,
        )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "You extract event information from Japanese entertainment content. Respond only with valid JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,  # Low temperature for consistent extraction
            max_tokens=2000,
        )

        result_text = response.choices[0].message.content.strip()

        # Extract token usage
        tokens_used = None
        if response.usage:
            tokens_used = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        # Log LLM response
        if logger:
            logger.log_llm_response(
                source_id=log_id,
                response=result_text,
                tokens_used=tokens_used,
                success=True,
            )

        # Try to parse JSON (handle potential markdown wrapping)
        if result_text.startswith("```"):
            # Remove markdown code blocks
            lines = result_text.split("\n")
            result_text = "\n".join(
                line for line in lines if not line.startswith("```")
            )

        result = json.loads(result_text)

        # Convert to Event objects
        events = []
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

    except json.JSONDecodeError as e:
        print(f"Error parsing LLM response as JSON: {e}")
        if logger:
            logger.log_llm_response(
                source_id=log_id,
                response=result_text if "result_text" in locals() else "",
                success=False,
                error=f"JSON decode error: {e}",
            )
        return None  # Return None to indicate failure
    except Exception as e:
        print(f"Error during extraction: {e}")
        if logger:
            logger.log_llm_response(
                source_id=log_id,
                response="",
                success=False,
                error=str(e),
            )
        return None  # Return None to indicate failure


def _parse_date(date_str: str | None) -> datetime | None:
    """Parse date string to datetime."""
    if not date_str:
        return None

    # Try different formats
    formats = [
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y/%m/%d",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue

    return None


def extract_events_from_sections(
    sections: list[str],
    artist_name: str,
    source_url: str,
    client: OpenAI | None = None,
    source_id: str | None = None,
) -> list[Event]:
    """Extract events from multiple content sections.

    Combines sections and extracts events in one call to save API costs.

    DEPRECATED: Use extract_events_from_section() for per-page extraction instead.
    This function is kept for backwards compatibility but per-page extraction
    is now the default to avoid context dilution.
    """
    if not sections:
        return []

    # Combine sections with separators
    combined = "\n---\n".join(sections)

    return extract_events(
        content=combined,
        artist_name=artist_name,
        source_url=source_url,
        client=client,
        source_id=source_id,
    )


def extract_events_from_section(
    section: str,
    artist_name: str,
    source_url: str,
    client: OpenAI,
    source_id: str,
    page_index: int = 0,
) -> list[Event] | None:
    """Extract events from a single section (detail page).

    This is the preferred extraction method. Each detail page is processed
    independently to avoid context dilution where lottery info from one
    event gets lost among content from other events.

    Args:
        section: Content from a single detail page
        artist_name: Name of the artist
        source_url: URL of the detail page
        client: OpenAI client
        source_id: Source identifier for logging
        page_index: Index of this page (for logging filenames)

    Returns:
        List of events extracted, empty list if none found, None if extraction failed.
    """
    logger = get_logger()

    # Extract the actual URL from the section header if present
    detail_url = source_url
    if section.startswith("=== Detail Page:"):
        # Parse URL from "=== Detail Page: https://... ==="
        first_line = section.split("\n")[0]
        url_match = (
            first_line.replace("=== Detail Page:", "").replace("===", "").strip()
        )
        if url_match:
            detail_url = url_match

    # Truncate content if too long
    max_content_length = 12000
    content = section
    if len(content) > max_content_length:
        content = content[:max_content_length] + "\n...[truncated]"

    prompt = EXTRACTION_PROMPT.format(
        source_url=detail_url,
        artist_name=artist_name,
        content=content,
    )

    model = "gpt-4o-mini"

    # Log LLM request with page index
    if logger:
        logger.log_llm_request(
            source_id=source_id,
            prompt=prompt,
            model=model,
            artist_name=artist_name,
            page_index=page_index,
        )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "You extract event information from Japanese entertainment content. Respond only with valid JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=2000,
        )

        result_text = response.choices[0].message.content.strip()

        # Extract token usage
        tokens_used = None
        if response.usage:
            tokens_used = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        # Log LLM response with page index
        if logger:
            logger.log_llm_response(
                source_id=source_id,
                response=result_text,
                tokens_used=tokens_used,
                success=True,
                page_index=page_index,
            )

        # Try to parse JSON (handle potential markdown wrapping)
        if result_text.startswith("```"):
            lines = result_text.split("\n")
            result_text = "\n".join(
                line for line in lines if not line.startswith("```")
            )

        result = json.loads(result_text)

        # Convert to Event objects
        events = []
        for e in result.get("events", []):
            try:
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
                    source_url=detail_url,
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

    except json.JSONDecodeError as e:
        print(f"Error parsing LLM response as JSON: {e}")
        if logger:
            logger.log_llm_response(
                source_id=source_id,
                response=result_text if "result_text" in locals() else "",
                success=False,
                error=f"JSON decode error: {e}",
                page_index=page_index,
            )
        return None
    except Exception as e:
        print(f"Error during extraction: {e}")
        if logger:
            logger.log_llm_response(
                source_id=source_id,
                response="",
                success=False,
                error=str(e),
                page_index=page_index,
            )
        return None
