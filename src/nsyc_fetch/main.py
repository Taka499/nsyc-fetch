"""Main entry point for NSYC Fetch."""

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv
from openai import OpenAI

from .extractor import extract_events_from_section
from .fetcher import discover_event_urls, fetch_detail_page
from .logger import close_logger, get_logger, init_logger
from .models import DetailPageState, Event, FetchState


def load_sources(config_path: str = "sources.yaml") -> dict:
    """Load sources configuration from YAML."""
    with open(config_path) as f:
        return yaml.safe_load(f)


def load_state(state_path: str = "state.json") -> FetchState:
    """Load persisted state from JSON file."""
    path = Path(state_path)
    if path.exists():
        with open(path) as f:
            data = json.load(f)
            return FetchState(**data)
    return FetchState()


def save_state(state: FetchState, state_path: str = "state.json") -> None:
    """Save state to JSON file."""
    with open(state_path, "w") as f:
        json.dump(state.model_dump(mode="json"), f, indent=2, default=str)


def load_events(events_path: str = "events.json") -> list[dict]:
    """Load existing events from JSON file."""
    path = Path(events_path)
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return []


def save_events(events: list[Event], events_path: str = "events.json") -> None:
    """Save events to JSON file, merging with existing events."""
    existing = load_events(events_path)

    # Convert new events to dicts
    new_event_dicts = [e.model_dump(mode="json") for e in events]

    # Create a set of existing event signatures for deduplication
    def event_signature(e: dict) -> str:
        return f"{e['artist']}|{e['title']}|{e['date']}"

    existing_signatures = {event_signature(e) for e in existing}

    # Add only new events
    added = 0
    for event_dict in new_event_dicts:
        sig = event_signature(event_dict)
        if sig not in existing_signatures:
            existing.append(event_dict)
            existing_signatures.add(sig)
            added += 1

    # Sort by date (upcoming first)
    existing.sort(key=lambda e: e.get("date", "9999-12-31"))

    with open(events_path, "w") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False, default=str)

    print(f"Added {added} new events. Total events: {len(existing)}")


def get_known_urls_for_source(
    state: FetchState,
    source_id: str,
    current_time: datetime,
) -> list[str]:
    """Get known detail page URLs for a source that are still active.

    A page is active if its event_date is in the future or not set.
    """
    known_urls = []
    for url, page_state in state.detail_pages.items():
        if page_state.source_id != source_id:
            continue
        # Include if event_date is None or in the future
        if page_state.event_date is None or page_state.event_date > current_time:
            known_urls.append(url)
    return known_urls


async def fetch_artist_events(
    artist_config: dict,
    openai_client: OpenAI,
    state: FetchState,
    force: bool = False,
) -> list[Event]:
    """Fetch and extract events for a single artist.

    Orchestrates the fetch → compare → extract flow:
    1. Get known URLs from state (still active)
    2. Discover new URLs from listing page
    3. Merge known + new URLs
    4. For each URL: fetch, compare hash, extract if changed
    5. Update state
    """
    artist_name = artist_config["name"]
    sources = artist_config.get("sources", [])
    all_events = []
    logger = get_logger()
    current_time = datetime.now()

    print(f"\n{'=' * 50}")
    print(f"Processing: {artist_name}")
    print(f"{'=' * 50}")

    for source in sources:
        source_id = source["id"]
        listing_url = source["url"]
        filter_keywords = source.get("filter_keywords", [])
        max_detail_pages = source.get("max_detail_pages", 10)

        print(f"\nSource: {source_id}")
        print(f"  Listing URL: {listing_url}")

        try:
            # Step 1: Get known URLs from state (still active)
            known_urls = get_known_urls_for_source(state, source_id, current_time)
            print(f"  Known active pages: {len(known_urls)}")

            # Step 2: Discover new URLs from listing page
            discovered_urls = await discover_event_urls(listing_url, filter_keywords)
            discovered_urls = discovered_urls[:max_detail_pages]
            print(f"  Discovered pages: {len(discovered_urls)}")

            # Step 3: Merge known + discovered (deduplicated)
            all_urls = list(dict.fromkeys(known_urls + discovered_urls))
            print(f"  Total pages to check: {len(all_urls)}")

            if not all_urls:
                print("  No pages to process")
                if logger:
                    logger.log_skip(source_id, "No pages to process")
                continue

            # Step 4: Fetch each page, compare hash, extract if changed
            source_events = []
            page_index = 0

            for url in all_urls:
                try:
                    # Fetch the page
                    page_content = await fetch_detail_page(url)
                    old_state = state.detail_pages.get(url)
                    old_hash = old_state.content_hash if old_state else None
                    is_new = old_state is None
                    has_changed = old_hash != page_content.content_hash

                    # Skip if unchanged (unless force mode)
                    if not force and not is_new and not has_changed:
                        print(f"    [{page_index}] {url[:50]}... (unchanged)")
                        page_index += 1
                        continue

                    status = "new" if is_new else "changed"
                    print(f"    [{page_index}] {url[:50]}... ({status})")

                    # Extract events from this page
                    events = extract_events_from_section(
                        section=page_content.content,
                        artist_name=artist_name,
                        source_url=url,
                        client=openai_client,
                        source_id=source_id,
                        page_index=page_index,
                    )

                    if events is None:
                        print("      Extraction failed")
                        if logger:
                            logger.log_error(source_id, f"Extraction failed: {url}")
                    else:
                        if events:
                            print(f"      Found {len(events)} events")
                            source_events.extend(events)

                            if logger:
                                logger.log_events(
                                    source_id=source_id,
                                    events=[e.model_dump(mode="json") for e in events],
                                    page_index=page_index,
                                )
                        else:
                            print("      No events found")

                        # Update state for this page
                        max_event_date = None
                        if events:
                            event_dates = [e.date for e in events if e.date]
                            if event_dates:
                                max_event_date = max(event_dates)

                        state.detail_pages[url] = DetailPageState(
                            url=url,
                            content_hash=page_content.content_hash,
                            last_checked=current_time,
                            event_date=max_event_date,
                            source_id=source_id,
                        )

                except Exception as e:
                    print(f"    [{page_index}] {url[:50]}... ERROR: {e}")
                    if logger:
                        logger.log_error(source_id, f"Failed to fetch {url}: {e}")

                page_index += 1

            print(f"  Extracted {len(source_events)} events from {source_id}")
            all_events.extend(source_events)

        except Exception as e:
            print(f"  Error processing source: {e}")
            if logger:
                logger.log_error(source_id, str(e))
            continue

    return all_events


async def run_fetch(
    config_path: str = "sources.yaml",
    state_path: str = "state.json",
    events_path: str = "events.json",
    force: bool = False,
) -> list[Event]:
    """Run the full fetch and extraction pipeline."""

    # Load environment
    load_dotenv()

    # Initialize logger
    logger = init_logger()
    print(f"Logs will be saved to: {logger.run_dir}")

    # Create OpenAI client
    openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    # Load configuration
    config = load_sources(config_path)
    state = load_state(state_path)

    print(f"Starting fetch at {datetime.now().isoformat()}")
    print(f"Last run: {state.last_run or 'never'}")

    # Fetch events for each artist
    all_events: list[Event] = []

    try:
        for artist_config in config.get("artists", []):
            events = await fetch_artist_events(
                artist_config=artist_config,
                openai_client=openai_client,
                state=state,
                force=force,
            )
            all_events.extend(events)

        # Update state
        state.last_run = datetime.now()

        # Save results
        if all_events:
            save_events(all_events, events_path)
        save_state(state, state_path)

    finally:
        # Always close logger and write summary
        close_logger()

    print(f"\n{'=' * 50}")
    print(f"Fetch complete. Found {len(all_events)} new events.")
    print(f"{'=' * 50}")

    return all_events


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Fetch events for tracked artists")
    parser.add_argument(
        "--config", default="sources.yaml", help="Path to sources configuration file"
    )
    parser.add_argument("--state", default="state.json", help="Path to state file")
    parser.add_argument(
        "--output", default="events.json", help="Path to output events file"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-extract even if content hasn't changed",
    )

    args = parser.parse_args()

    # If force, clear detail page hashes so everything is re-extracted
    force = args.force
    if force:
        state = load_state(args.state)
        state.detail_pages = {}
        save_state(state, args.state)
        print("Cleared detail page state, will re-extract all pages")

    # Run async fetch
    events = asyncio.run(
        run_fetch(
            config_path=args.config,
            state_path=args.state,
            events_path=args.output,
            force=force,
        )
    )

    # Print summary of upcoming events
    if events:
        print("\nUpcoming events:")
        for event in sorted(events, key=lambda e: e.date):
            deadline_str = ""
            if event.action_required and event.action_deadline:
                deadline_str = (
                    f" [ACTION by {event.action_deadline.strftime('%Y-%m-%d')}]"
                )
            print(
                f"  - {event.date.strftime('%Y-%m-%d')} | {event.artist} | {event.title}{deadline_str}"
            )


if __name__ == "__main__":
    main()
