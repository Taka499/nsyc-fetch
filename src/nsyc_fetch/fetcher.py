"""Fetch content from web sources.

This module provides stateless fetching functions:
- discover_event_urls(): Find event detail page URLs from a listing page
- fetch_detail_page(): Fetch a single detail page and return content + hash

The orchestrator (main.py) handles all state logic: comparing hashes,
deciding what to extract, and updating state.
"""

import hashlib
import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from .models import DetailPageContent


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


def compute_content_hash(content: str) -> str:
    """Compute hash of content for change detection."""
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _extract_event_links(
    html: str, base_url: str, filter_keywords: list[str] | None = None
) -> list[str]:
    """Extract links to event detail pages from a listing page HTML.

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


def _extract_detail_page_content(html: str) -> str:
    """Extract the main content from an event detail page HTML.

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


# =============================================================================
# Public API: Two simple stateless functions
# =============================================================================


async def discover_event_urls(
    listing_url: str,
    filter_keywords: list[str] | None = None,
) -> list[str]:
    """Fetch listing page and return discovered event detail page URLs.

    Args:
        listing_url: URL of the listing page (e.g., /events or /news)
        filter_keywords: Optional keywords to filter relevant links

    Returns:
        List of absolute URLs to event detail pages
    """
    html = await fetch_webpage(listing_url)
    return _extract_event_links(html, listing_url, filter_keywords)


async def fetch_detail_page(url: str) -> DetailPageContent:
    """Fetch a single detail page and return structured content.

    Args:
        url: URL of the detail page to fetch

    Returns:
        DetailPageContent with url, content, and content_hash
    """
    html = await fetch_webpage(url)
    content = _extract_detail_page_content(html)
    content_hash = compute_content_hash(content)
    return DetailPageContent(url=url, content=content, content_hash=content_hash)
