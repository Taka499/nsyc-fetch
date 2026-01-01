"""Extract events from content using LLM."""

import json
import os
from datetime import datetime

from openai import OpenAI

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
9. action_description: What action is needed (e.g., "Apply for lottery", "Purchase tickets")
10. event_url: URL for event details (optional)
11. ticket_url: URL for ticket purchase (optional)

Pay special attention to:
- 先行抽選 / 抽選 (lottery) - note the application period as a separate "lottery" event
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
    "event_type": "live",
    "title": "Event Title",
    "date": "2025-01-15",
    "end_date": null,
    "venue": "Venue Name",
    "location": "Tokyo",
    "action_required": true,
    "action_deadline": "2025-01-01",
    "action_description": "Apply for lottery",
    "event_url": "https://...",
    "ticket_url": "https://..."
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
) -> list[Event]:
    """Extract events from content using LLM.

    Args:
        content: Text content to analyze
        artist_name: Name of the artist to look for
        source_url: URL where content was fetched from
        client: OpenAI client (created if not provided)
        model: Model to use for extraction

    Returns:
        List of extracted Event objects
    """
    if client is None:
        client = create_openai_client()

    # Truncate content if too long (leave room for prompt)
    max_content_length = 12000
    if len(content) > max_content_length:
        content = content[:max_content_length] + "\n...[truncated]"

    prompt = EXTRACTION_PROMPT.format(
        source_url=source_url,
        artist_name=artist_name,
        content=content,
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
                event = Event(
                    artist=artist_name,
                    event_type=EventType(e.get("event_type", "other")),
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
        return None  # Return None to indicate failure
    except Exception as e:
        print(f"Error during extraction: {e}")
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
    )
