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
from .fetcher import fetch_source
from .logger import close_logger, get_logger, init_logger
from .models import Event, FetchState


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


async def fetch_artist_events(
    artist_config: dict,
    openai_client: OpenAI,
    state: FetchState,
) -> list[Event]:
    """Fetch and extract events for a single artist."""
    artist_name = artist_config["name"]
    sources = artist_config.get("sources", [])
    all_events = []
    logger = get_logger()

    print(f"\n{'=' * 50}")
    print(f"Processing: {artist_name}")
    print(f"{'=' * 50}")

    for source in sources:
        source_id = source["id"]
        url = source["url"]
        filter_keywords = source.get("filter_keywords", [])
        fetch_detail = source.get("fetch_detail_pages", True)
        max_detail_pages = source.get("max_detail_pages", 10)

        print(f"\nFetching: {source_id}")
        print(f"  URL: {url}")
        print(f"  Detail pages: {'enabled' if fetch_detail else 'disabled'}")

        try:
            # Fetch content
            content = await fetch_source(
                source_id=source_id,
                url=url,
                filter_keywords=filter_keywords,
                fetch_detail_pages=fetch_detail,
                max_detail_pages=max_detail_pages,
            )

            # Log fetched content
            combined = "\n---\n".join(content.relevant_sections)
            detail_count = sum(
                1 for s in content.relevant_sections if s.startswith("=== Detail Page:")
            )
            if logger:
                logger.log_fetch(
                    source_id=source_id,
                    url=url,
                    sections=content.relevant_sections,
                    combined_content=combined,
                    content_hash=content.content_hash,
                    detail_pages_fetched=detail_count,
                )

            # Check if content changed
            old_hash = state.source_hashes.get(source_id)
            if old_hash == content.content_hash:
                print(f"  No changes detected (hash: {content.content_hash[:8]})")
                if logger:
                    logger.log_skip(source_id, "Content unchanged")
                continue

            print(f"  Content changed (hash: {content.content_hash[:8]})")
            print(f"  Found {len(content.relevant_sections)} relevant sections")

            # Extract events using per-page extraction
            # Each detail page is processed independently to avoid context dilution
            detail_sections = [
                s for s in content.relevant_sections if s.startswith("=== Detail Page:")
            ]

            if detail_sections:
                source_events = []
                extraction_failed = False
                page_index = 0

                for section in detail_sections:
                    # Extract URL from section header for logging
                    first_line = section.split("\n")[0]
                    detail_url = first_line.replace("=== Detail Page:", "").replace("===", "").strip()
                    print(f"    Extracting from page {page_index}: {detail_url[:60]}...")

                    events = extract_events_from_section(
                        section=section,
                        artist_name=artist_name,
                        source_url=url,
                        client=openai_client,
                        source_id=source_id,
                        page_index=page_index,
                    )

                    if events is None:
                        # Extraction failed for this page
                        print(f"    Extraction failed for page {page_index}")
                        extraction_failed = True
                    elif events:
                        print(f"    Found {len(events)} events")
                        source_events.extend(events)

                        # Log extracted events for this page
                        if logger:
                            logger.log_events(
                                source_id=source_id,
                                events=[e.model_dump(mode="json") for e in events],
                                page_index=page_index,
                            )
                    else:
                        print("    No events found")

                    page_index += 1

                if extraction_failed:
                    # At least one extraction failed - don't update hash, retry next run
                    print("  Some extractions failed - will retry next run")
                    if logger:
                        logger.log_error(source_id, "Some page extractions failed")
                    # Still add successfully extracted events
                    all_events.extend(source_events)
                    continue

                print(f"  Extracted {len(source_events)} total events from {len(detail_sections)} pages")
                all_events.extend(source_events)

                # Only update hash after all extractions succeed
                state.source_hashes[source_id] = content.content_hash
            else:
                print("  No detail page sections found")
                if logger:
                    logger.log_skip(source_id, "No detail page sections")
                # Still update hash if no sections (nothing to extract)
                state.source_hashes[source_id] = content.content_hash

        except Exception as e:
            print(f"  Error: {e}")
            if logger:
                logger.log_error(source_id, str(e))
            continue

    return all_events


async def run_fetch(
    config_path: str = "sources.yaml",
    state_path: str = "state.json",
    events_path: str = "events.json",
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
        help="Force re-fetch even if content hasn't changed",
    )

    args = parser.parse_args()

    # If force, clear state hashes
    if args.force:
        state = load_state(args.state)
        state.source_hashes = {}
        save_state(state, args.state)
        print("Cleared content hashes, will re-fetch all sources")

    # Run async fetch
    events = asyncio.run(
        run_fetch(
            config_path=args.config,
            state_path=args.state,
            events_path=args.output,
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
