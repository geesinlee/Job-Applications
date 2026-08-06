"""LinkedIn job-alert email parser.

Extracts structured job cards from LinkedIn job-alert email HTML.
Supports both digest ("X jobs matching your search") and single-job
("New job for you" / "Recommended job") email formats.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse, parse_qs

from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

# Maximum snippet length before truncation
_MAX_SNIPPET = 200

# Regex for LinkedIn job URLs
_JOB_VIEW_RE = re.compile(r"linkedin\.com/jobs/view/\d+", re.IGNORECASE)
_JOB_SEARCH_RE = re.compile(r"linkedin\.com/jobs/search/", re.IGNORECASE)

# Known location keywords to detect from free text
_LOCATION_KEYWORDS_RE = re.compile(
    r"\b(Singapore|Remote|Hybrid|APAC|ASEAN|Asia.?Pacific|United States|USA|UK|Europe|EMEA)\b",
    re.IGNORECASE,
)


@dataclass
class JobCard:
    """A single job extracted from a LinkedIn alert email."""

    title: str
    company: str
    location: str | None
    url: str
    snippet: str  # max 200 chars, truncated with "..."
    source_email_id: str  # Gmail message ID
    source_date: str  # ISO-8601 email date


def _truncate_snippet(text: str) -> str:
    """Truncate snippet to _MAX_SNIPPET chars, appending '...' if truncated."""
    text = text.strip()
    if len(text) <= _MAX_SNIPPET:
        return text
    return text[: _MAX_SNIPPET - 3] + "..."


def _extract_job_id(url: str) -> str | None:
    """Extract numeric job ID from a LinkedIn URL, if present."""
    # /jobs/view/12345
    m = re.search(r"/jobs/view/(\d+)", url)
    if m:
        return m.group(1)
    # /jobs/search/?...&currentJobId=12345
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    job_id_list = params.get("currentJobId", [])
    if job_id_list:
        return job_id_list[0]
    return None


def _find_job_links(soup: BeautifulSoup) -> list[Tag]:
    """Find all <a> tags that point to LinkedIn job pages."""
    links: list[Tag] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if _JOB_VIEW_RE.search(href) or _JOB_SEARCH_RE.search(href):
            links.append(a)
    return links


def _find_card_container(tag: Tag) -> Tag:
    """Walk up from a link to find the nearest meaningful card container.

    A card container is a parent element that has substantially more text
    content than just the link title — it likely holds company, location,
    and snippet fields too.
    """
    current = tag.parent
    while current is not None:
        if isinstance(current, Tag):
            link_text = tag.get_text(strip=True)
            container_text = current.get_text(strip=True)
            # The container should have more text than just the link title
            # (company + location + snippet add meaningful length)
            if len(container_text) > len(link_text) * 2:
                return current
        current = current.parent if hasattr(current, "parent") else None
    # Fallback: return the link's immediate parent
    return tag.parent if tag.parent else tag


def _extract_company(card: Tag) -> str:
    """Extract company name from a card container."""
    # Try <span class="company"> first
    company_span = card.find("span", class_="company")
    if company_span:
        return company_span.get_text(strip=True)

    # Fallback: look for text that looks like a company name on the next line
    # after the title link. Only consider <span> or <div> elements (not <p>,
    # which is the snippet). Skip <span class="location">.
    def _is_company_candidate(tag: Tag) -> bool:
        """Return True if the tag could hold a company name (not snippet/location)."""
        if tag.name == "p":
            return False  # <p> is snippet territory
        classes = tag.get("class", [])
        if isinstance(classes, str):
            classes = [classes]
        if "location" in classes:
            return False
        return True

    links = card.find_all("a", href=True)
    for link in links:
        if _JOB_VIEW_RE.search(link["href"]) or _JOB_SEARCH_RE.search(link["href"]):
            # Check next sibling elements
            for sibling in link.next_siblings:
                if isinstance(sibling, Tag) and _is_company_candidate(sibling):
                    text = sibling.get_text(strip=True)
                    if text and not _LOCATION_KEYWORDS_RE.search(text):
                        return text
            # Also check parent's direct children after the link
            parent = link.parent
            if parent and isinstance(parent, Tag):
                found_link = False
                for child in parent.children:
                    if child is link:
                        found_link = True
                        continue
                    if found_link and isinstance(child, Tag) and _is_company_candidate(child):
                        text = child.get_text(strip=True)
                        if text and not _LOCATION_KEYWORDS_RE.search(text):
                            return text

    return "Unknown"


def _extract_location(card: Tag) -> str | None:
    """Extract location from a card container."""
    # Try <span class="location"> first
    location_span = card.find("span", class_="location")
    if location_span:
        return location_span.get_text(strip=True)

    # Fallback: search for known location keywords in text nodes
    text = card.get_text(separator=" ", strip=True)
    match = _LOCATION_KEYWORDS_RE.search(text)
    if match:
        # Return the broader match context (e.g., "Remote, APAC" not just "Remote")
        # Find the containing phrase — look for text node containing the keyword
        for span in card.find_all(["span", "div", "p"]):
            span_text = span.get_text(strip=True)
            if _LOCATION_KEYWORDS_RE.search(span_text):
                return span_text

    return None


def _extract_snippet(card: Tag) -> str:
    """Extract snippet from a card container."""
    # Try <p class="snippet"> first
    snippet_p = card.find("p", class_="snippet")
    if snippet_p:
        return _truncate_snippet(snippet_p.get_text(strip=True))

    # Fallback: look for any <p> tag in the card
    for p in card.find_all("p"):
        text = p.get_text(strip=True)
        if text:
            return _truncate_snippet(text)

    return ""


def parse_linkedin_email(
    html: str | None,
    source_email_id: str,
    source_date: str,
) -> list[JobCard]:
    """Parse a LinkedIn job-alert email HTML and extract job cards.

    Args:
        html: Raw HTML string from the email body. None or empty returns [].
        source_email_id: Gmail message ID for traceability.
        source_date: ISO-8601 date string of the email.

    Returns:
        List of JobCard instances. Empty list if parsing fails or no jobs found.
    """
    if not html:
        return []

    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        logger.warning("Failed to parse HTML for email %s", source_email_id)
        return []

    links = _find_job_links(soup)
    if not links:
        return []

    cards: list[JobCard] = []
    for link in links:
        try:
            url = link["href"]
            title = link.get_text(strip=True)

            if not title:
                logger.debug(
                    "Skipping link with empty title in email %s", source_email_id
                )
                continue

            # Deduplicate by URL
            if any(c.url == url for c in cards):
                continue

            container = _find_card_container(link)
            company = _extract_company(container)
            location = _extract_location(container)
            snippet = _extract_snippet(container)

            # If snippet is the same as title text (no dedicated snippet element),
            # clear it — we only want description text, not the repeated title
            if snippet == title:
                snippet = ""

            cards.append(
                JobCard(
                    title=title,
                    company=company,
                    location=location,
                    url=url,
                    snippet=snippet,
                    source_email_id=source_email_id,
                    source_date=source_date,
                )
            )
        except Exception:
            logger.warning(
                "Failed to extract job card from link in email %s",
                source_email_id,
                exc_info=True,
            )
            continue

    return cards