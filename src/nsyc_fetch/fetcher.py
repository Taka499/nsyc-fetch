"""Fetch content from web sources."""

import hashlib
import re
from datetime import datetime
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from .models import SourceContent


async def fetch_webpage(url: str, timeout: float = 30.0) -> str:
    """Fetch raw HTML from a URL."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja,en;q=0.9",
    }

    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        return response.text


def extract_text_content(html: str) -> str:
    """Extract readable text from HTML."""
    soup = BeautifulSoup(html, "lxml")

    # Remove script and style elements
    for element in soup(["script", "style", "nav", "footer", "header"]):
        element.decompose()

    # Get text
    text = soup.get_text(separator="\n", strip=True)

    # Clean up whitespace
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def extract_event_links(
    html: str, base_url: str, filter_keywords: list[str] | None = None
) -> list[str]:
    """Extract links to event detail pages from a listing page.

    Returns list of absolute URLs to event detail pages.
    """
    soup = BeautifulSoup(html, "lxml")
    links = []

    # Find links that look like event detail pages
    # BanG Dream pattern: /events/something or /news/something
    for a_tag in soup.find_all("a", href=re.compile(r"/(events|news)/[^/]+$")):
        href = a_tag.get("href")
        if not href:
            continue

        # Make absolute URL
        full_url = urljoin(base_url, href)

        # Apply keyword filter if provided
        if filter_keywords:
            # Check if any keyword appears in the link text or nearby content
            link_text = a_tag.get_text(strip=True)
            parent_text = a_tag.parent.get_text(strip=True) if a_tag.parent else ""
            combined_text = f"{link_text} {parent_text}".lower()

            if any(kw.lower() in combined_text for kw in filter_keywords):
                links.append(full_url)
        else:
            links.append(full_url)

    # Deduplicate while preserving order
    seen = set()
    unique_links = []
    for link in links:
        if link not in seen:
            seen.add(link)
            unique_links.append(link)

    return unique_links[:20]  # Limit to 20 detail pages


def extract_event_sections(
    html: str, filter_keywords: list[str] | None = None
) -> list[str]:
    """Extract sections that look like event listings."""
    soup = BeautifulSoup(html, "lxml")
    sections = []

    # Look for common event container patterns
    # BanG Dream! site uses article/section/div with specific classes
    event_containers = soup.find_all(
        ["article", "section", "div"],
        class_=re.compile(r"event|news|live|schedule", re.I),
    )

    if not event_containers:
        # Fallback: look for links containing event-related keywords
        event_containers = soup.find_all(
            "a", href=re.compile(r"/events/|/news/|/live/")
        )

    for container in event_containers:
        text = container.get_text(separator=" ", strip=True)

        # Apply keyword filter if provided
        if filter_keywords:
            if any(kw.lower() in text.lower() for kw in filter_keywords):
                sections.append(text[:2000])  # Limit length
        else:
            sections.append(text[:2000])

    # Deduplicate while preserving order
    seen = set()
    unique_sections = []
    for s in sections:
        if s not in seen:
            seen.add(s)
            unique_sections.append(s)

    return unique_sections[:20]  # Limit to 20 sections


def extract_detail_page_content(html: str) -> str:
    """Extract the main content from an event detail page.

    More aggressive extraction focused on the main content area.
    """
    soup = BeautifulSoup(html, "lxml")

    # Remove non-content elements
    for element in soup(["script", "style", "nav", "footer", "header", "aside"]):
        element.decompose()

    # Try to find main content area
    main_content = None

    # Common patterns for main content
    for selector in [
        {"class_": re.compile(r"main|content|article|event|detail", re.I)},
        {"id": re.compile(r"main|content|article", re.I)},
        {"role": "main"},
    ]:
        main_content = soup.find(["main", "article", "div", "section"], **selector)
        if main_content:
            break

    if main_content:
        text = main_content.get_text(separator="\n", strip=True)
    else:
        # Fallback to body
        text = soup.get_text(separator="\n", strip=True)

    # Clean up whitespace
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def compute_content_hash(content: str) -> str:
    """Compute hash of content for change detection."""
    return hashlib.sha256(content.encode()).hexdigest()[:16]


async def fetch_source(
    source_id: str,
    url: str,
    filter_keywords: list[str] | None = None,
    fetch_detail_pages: bool = True,
    max_detail_pages: int = 10,
) -> SourceContent:
    """Fetch and process a single source.

    Args:
        source_id: Unique identifier for this source
        url: URL to fetch
        filter_keywords: Keywords to filter relevant content
        fetch_detail_pages: If True, also fetch linked detail pages
        max_detail_pages: Maximum number of detail pages to fetch

    Returns:
        SourceContent with extracted text and sections
    """

    # Fetch listing page
    html = await fetch_webpage(url)
    text = extract_text_content(html)
    sections = extract_event_sections(html, filter_keywords)

    # Fetch detail pages if enabled
    detail_contents = []
    detail_page_hashes: dict[str, str] = {}
    if fetch_detail_pages:
        event_links = extract_event_links(html, url, filter_keywords)
        print(f"    Found {len(event_links)} detail page links")

        for i, link in enumerate(event_links[:max_detail_pages]):
            try:
                print(f"    Fetching detail page {i + 1}: {link}")
                detail_html = await fetch_webpage(link)
                detail_text = extract_detail_page_content(detail_html)
                detail_contents.append(f"=== Detail Page: {link} ===\n{detail_text}")
                # Store per-page hash for state tracking
                detail_page_hashes[link] = compute_content_hash(detail_text)
            except Exception as e:
                print(f"    Failed to fetch {link}: {e}")
                continue

    # Combine listing sections with detail page contents
    all_sections = sections + detail_contents

    # Hash based on all content
    combined_text = text + "\n".join(detail_contents)
    content_hash = compute_content_hash(combined_text)

    return SourceContent(
        source_id=source_id,
        url=url,
        fetched_at=datetime.now(),
        content_hash=content_hash,
        raw_html=html,
        extracted_text=text,
        relevant_sections=all_sections,
        detail_page_hashes=detail_page_hashes,
    )
