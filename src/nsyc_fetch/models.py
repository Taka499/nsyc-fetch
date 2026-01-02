"""Data models for NSYC Fetch."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class EventType(str, Enum):
    LIVE = "live"  # Concert, live performance
    RELEASE = "release"  # CD, album, single release
    LOTTERY = "lottery"  # Ticket lottery period
    SALE = "sale"  # Ticket general sale
    BROADCAST = "broadcast"  # TV, streaming, radio
    STREAMING = "streaming"  # Online streaming of live
    SCREENING = "screening"  # Movie theater screening
    OTHER = "other"


class Event(BaseModel):
    """A time-bound event that the user should know about."""

    artist: str = Field(description="Artist or band name")
    event_type: EventType = Field(description="Type of event")
    title: str = Field(description="Event title")

    # Dates
    date: datetime = Field(description="Event date or start date")
    end_date: datetime | None = Field(
        default=None, description="End date for multi-day events or lottery periods"
    )

    # Location (for live events)
    venue: str | None = Field(default=None, description="Venue name")
    location: str | None = Field(default=None, description="City or area")

    # Action info
    action_required: bool = Field(
        default=False, description="True if user needs to take action"
    )
    action_deadline: datetime | None = Field(
        default=None, description="Deadline for user action"
    )
    action_description: str | None = Field(
        default=None, description="What action is needed"
    )

    # URLs
    event_url: str | None = Field(default=None, description="Official event page URL")
    ticket_url: str | None = Field(default=None, description="Ticket purchase URL")

    # Metadata
    source_url: str = Field(description="URL where this info was found")
    extracted_at: datetime = Field(default_factory=datetime.now)
    raw_text: str | None = Field(default=None, description="Original text snippet")

    # Lifecycle
    ended: bool = Field(
        default=False,
        description="True if event has passed or action window closed",
    )


class DetailPageContent(BaseModel):
    """Content fetched from a single detail page."""

    url: str = Field(description="URL of the detail page")
    content: str = Field(description="Extracted text content")
    content_hash: str = Field(description="Hash for change detection")


class DetailPageState(BaseModel):
    """State for tracking individual detail pages.

    Used to detect when known detail pages change (e.g., lottery ends,
    new ticket sale opens) so we can re-extract and update events.
    """

    url: str = Field(description="URL of the detail page")
    content_hash: str = Field(description="Hash of page content for change detection")
    last_checked: datetime = Field(description="When this page was last fetched")
    event_date: datetime | None = Field(
        default=None,
        description="Latest event date from this page; stop monitoring after this passes",
    )
    source_id: str = Field(description="Which source this page belongs to")


class FetchState(BaseModel):
    """Persisted state to track what we've seen."""

    last_run: datetime | None = None
    detail_pages: dict[str, DetailPageState] = Field(
        default_factory=dict
    )  # url -> DetailPageState
    seen_event_ids: list[str] = Field(default_factory=list)  # For future deduplication
