"""Extract events from content using LLM."""

import json
import os
from datetime import datetime

from openai import OpenAI

from .logger import get_logger
from .models import Event, EventType

EXTRACTION_PROMPT = """You are an event extraction assistant for Japanese entertainment content.
Given the following content from {source_url}, extract any time-bound events related to the artist "{artist_name}".

For each event found, extract:
1. event_type: One of: live, release, lottery, sale, broadcast, streaming, screening, other
2. title: Event title (in original language)
3. date: Event date (ISO format: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
4. end_date: End date if it's a multi-day event or period (optional)
5. venue: Venue name (optional, for live events)
6. location: City/area (optional)
7. action_required: true if user needs to take action (buy tickets, apply for lottery, etc.)
8. action_deadline: Deadline for action if applicable (ISO format)
9. action_description: What action is needed - BE SPECIFIC about prerequisites
10. event_url: URL for event details (optional)
11. ticket_url: URL for ticket purchase (optional)

IMPORTANT - Ticket Lottery Patterns (先行抽選):

Japanese events often have multiple lottery/sale phases. Create SEPARATE events for each phase:

1. CD先行/シリアル先行 (CD Priority Lottery):
   When you see patterns like:
   - "○○に封入の申込券でご応募" (apply using voucher included in ○○)
   - "シリアルコードでご応募" (apply using serial code)
   - "初回生産分" or "初回限定盤" (first-press or limited edition)

   This means lottery requires purchasing a specific product FIRST.
   Extract as event_type: "lottery" with action_description that includes:
   - The product name (e.g., "8th Single「静降想」")
   - That it requires the serial code/voucher from that product
   Example: "Apply for lottery using serial code from 8th Single (first-press edition)"

2. 最速先行 / FC先行 (Priority Lottery):
   Fan club or fastest priority lottery. Note any membership requirements.

3. 一般発売 (General Sale):
   Regular ticket sales, extract as event_type: "sale"

4. プレイガイド先行 (Playguide Priority):
   Priority lottery through ticket vendors, no product required.
   Extract as event_type: "lottery"

CRITICAL: For each concert/live, you MUST create SEPARATE events:
- One "live" event for the actual concert (action_required: false)
- One "lottery" event for EACH ticket lottery/sale phase with:
  - date/end_date = the APPLICATION PERIOD (not the concert date)
  - action_deadline = when applications close
  - action_description = specific requirements (CD name, lottery type, etc.)

DO NOT put lottery information on the "live" event. Create separate "lottery" events.

Pay special attention to:
- 先行抽選 / 抽選 (lottery) - extract application period as "lottery" event
- 先行発売 / 一般発売 (ticket sales) - note as "sale" event type
- ライブ / LIVE / 公演 (concerts) - note as "live" event type
- CD / アルバム / シングル releases - note as "release" event type
- 配信 / Streaming (online viewing) - note as "streaming" event type

Content to analyze:
---
{content}
---

Respond ONLY with a JSON object in this exact format (no markdown, no explanation):
{{"events": [
  {{
    "event_type": "lottery",
    "title": "Artist Name 9th LIVE 最速先行抽選",
    "date": "2025-12-06",
    "end_date": "2026-02-02",
    "venue": null,
    "location": null,
    "action_required": true,
    "action_deadline": "2026-02-02T23:59:00",
    "action_description": "Apply using serial code from 8th Single (first-press)",
    "event_url": "https://...",
    "ticket_url": "https://..."
  }},
  {{
    "event_type": "live",
    "title": "Artist Name 9th LIVE",
    "date": "2026-07-18",
    "end_date": "2026-07-19",
    "venue": "Venue Name",
    "location": "Yokohama",
    "action_required": false,
    "action_deadline": null,
    "action_description": null,
    "event_url": "https://...",
    "ticket_url": null
  }}
]}}

If no events are found, respond with: {{"events": []}}
"""


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
                )
                events.append(event)
            except Exception as e:
                print(f"Warning: Failed to parse event: {e}")
                continue

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
