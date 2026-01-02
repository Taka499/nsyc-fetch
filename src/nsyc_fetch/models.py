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


class EventList(BaseModel):
    """List of events extracted from a source."""

    events: list[Event] = Field(default_factory=list)


class SourceContent(BaseModel):
    """Content fetched from a source."""

    source_id: str
    url: str
    fetched_at: datetime
    content_hash: str  # For change detection (combined hash of all content)
    raw_html: str | None = None
    extracted_text: str | None = None
    relevant_sections: list[str] = Field(default_factory=list)
    detail_page_hashes: dict[str, str] = Field(
        default_factory=dict
    )  # url -> content_hash for each detail page


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
    source_hashes: dict[str, str] = Field(
        default_factory=dict
    )  # source_id -> content_hash
    detail_pages: dict[str, DetailPageState] = Field(
        default_factory=dict
    )  # url -> DetailPageState
    seen_event_ids: list[str] = Field(default_factory=list)  # To avoid duplicate events
