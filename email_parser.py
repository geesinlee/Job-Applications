"""LinkedIn job-alert email parser.

Extracts structured job cards from LinkedIn job-alert email HTML.
Supports both digest ("X jobs matching your search") and single-job
("New job for you" / "Recommended job") email formats.

LinkedIn email formats (as of 2026):
- Digest format: multiple job cards, each with title link, company+location
  in a <p> element separated by '·', and an "Apply" or "View job" link.
- Single-job format: one job card with similar structure.
- Link patterns: /comm/jobs/view/{id} (email redirect prefix) or /jobs/view/{id}
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
# Note: LinkedIn email links use /comm/ prefix (e.g., linkedin.com/comm/jobs/view/123)
_JOB_VIEW_RE = re.compile(r"linkedin\.com/(?:comm/)?jobs/view/\d+", re.IGNORECASE)
_JOB_SEARCH_RE = re.compile(r"linkedin\.com/(?:comm/)?jobs/search/", re.IGNORECASE)

# Known location keywords to detect from free text
_LOCATION_KEYWORDS_RE = re.compile(
    r"\b(Singapore|Remote|Hybrid|APAC|ASEAN|Asia.?Pacific|United States|USA|UK|Europe|EMEA)\b",
    re.IGNORECASE,
)

# Pattern to split "Company · Location" text
_COMPANY_LOCATION_SPLIT = re.compile(r"\s*·\s*")


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


def _parse_company_location(text: str) -> tuple[str, str | None]:
    """Parse 'Company · Location' or 'Company · Location (Remote)' text.

    Returns (company, location) tuple. If no '·' separator is found,
    returns (text, None).
    """
    parts = _COMPANY_LOCATION_SPLIT.split(text.strip(), maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return text.strip(), None


# Trailing status/badge text that LinkedIn sometimes renders after location
_LOCATION_NOISE_RE = re.compile(
    r"(?:Actively recruiting|Be an early applicant|Easy Apply|\d+\s+(?:connection|connections|company alum|company alumni|school alum|school alumni)).*$",
    re.IGNORECASE,
)

# Generic CTA link texts that should never replace a job title
_CTA_TEXTS = {
    "apply",
    "apply now",
    "easy apply",
    "view job",
    "view",
    "learn more",
    "see job",
}


def _clean_location(location: str | None) -> str | None:
    """Strip LinkedIn status/badge noise from extracted location text."""
    if not location:
        return None
    cleaned = _LOCATION_NOISE_RE.sub("", location).strip()
    return cleaned or None


def _link_job_key(link: Tag) -> str | None:
    """Return a canonical job identity key for a LinkedIn job link tag."""
    href = link.get("href", "")
    if not href or not isinstance(href, str):
        return None
    if not (_JOB_VIEW_RE.search(href) or _JOB_SEARCH_RE.search(href)):
        return None
    job_id = _extract_job_id(href)
    return f"id:{job_id}" if job_id else f"url:{href}"


def _distinct_job_keys(container: Tag) -> set[str]:
    """Return all distinct job identity keys found within container."""
    keys: set[str] = set()
    if container.name == "a":
        k = _link_job_key(container)
        if k:
            keys.add(k)
    for a in container.find_all("a", href=True):
        k = _link_job_key(a)
        if k:
            keys.add(k)
    return keys


def _has_card_metadata(container: Tag) -> bool:
    """Return True if container holds company, location, or snippet elements."""
    if container.find("span", class_="company"):
        return True
    if container.find("span", class_="location"):
        return True
    if container.find("p", class_="snippet"):
        return True
    for p in container.find_all("p"):
        p_text = p.get_text(strip=True)
        if "·" in p_text and len(p_text) < 200:
            return True
    return False


def _extract_title_from_link(link: Tag) -> str:
    """Extract clean job title from a job link tag.

    When a LinkedIn card link wraps multiple child elements (e.g. title
    plus '<p>Company · Location</p>' and status lines), avoid concatenating
    the metadata paragraphs into the title.
    """
    p_tags = link.find_all("p")
    if p_tags and any("·" in p.get_text(strip=True) for p in p_tags):
        title_parts: list[str] = []
        for p in p_tags:
            p_text = p.get_text(strip=True)
            if "·" in p_text:
                break
            if p_text:
                title_parts.append(p_text)
        if title_parts:
            return " ".join(title_parts)

        first_dot_p = next(p for p in p_tags if "·" in p.get_text(strip=True))
        dot_p_text = first_dot_p.get_text(strip=True)
        full_text = link.get_text("\n", strip=True)
        before_dot = full_text.split(dot_p_text, 1)[0].strip()
        if before_dot:
            return " ".join(before_dot.splitlines()).strip()

    return link.get_text(strip=True)


def _extract_card_from_link(link: Tag) -> Tag:
    """Walk up from a link to find the nearest single-job card container.

    Never walks into an ancestor that contains links for other jobs
    (len(_distinct_job_keys(current)) > 1), preventing cross-card
    company/location bleed in multi-job digest emails.
    """
    best: Tag = link
    current = link.parent
    while current is not None:
        if isinstance(current, Tag):
            if current.name in ("body", "html", "[document]"):
                break
            if len(_distinct_job_keys(current)) > 1:
                break
            if best is not link and current.find(["h1", "h2"]) is not None:
                break
            best = current
            if _has_card_metadata(best):
                return best
        current = current.parent if hasattr(current, "parent") else None
    return best


def _extract_company_from_card(card: Tag, title: str) -> str:
    """Extract company name from a card container.

    LinkedIn email formats vary:
    - 2026 digest format: <p class="text-system-gray-100 text-xs ..."> containing "Company · Location"
    - Older format: <span class="company">Company</span>
    """
    # Method 1: Explicit <span class="company"> element (older format)
    company_span = card.find("span", class_="company")
    if company_span:
        return company_span.get_text(strip=True)

    # Method 2: <p> elements with · separator (2026 digest format)
    for p in card.find_all("p"):
        p_text = p.get_text(strip=True)
        if "·" in p_text and len(p_text) < 200:
            company, _ = _parse_company_location(p_text)
            if company and company != title:
                return company

    # Method 3: Check sibling elements after the title link
    links = card.find_all("a", href=True)
    for link_tag in links:
        if _JOB_VIEW_RE.search(link_tag["href"]) or _JOB_SEARCH_RE.search(link_tag["href"]):
            for sibling in link_tag.next_siblings:
                if isinstance(sibling, Tag):
                    text = sibling.get_text(strip=True)
                    if text and "·" in text:
                        company, _ = _parse_company_location(text)
                        if company:
                            return company

    return "Unknown"


def _extract_location_from_card(card: Tag) -> str | None:
    """Extract location from a card container.

    Supports both:
    - <span class="location"> element (older format)
    - <p> with "Company · Location" pattern (2026 format)
    """
    # Method 0: Explicit <span class="location"> element (older format)
    location_span = card.find("span", class_="location")
    if location_span:
        return _clean_location(location_span.get_text(strip=True))

    # Method 1: <p> elements with · separator (2026 format)
    for p in card.find_all("p"):
        p_text = p.get_text(strip=True)
        if "·" in p_text:
            _, location = _parse_company_location(p_text)
            if location and _LOCATION_KEYWORDS_RE.search(location):
                return _clean_location(location)

    # Method 2: Search for known location keywords in any text
    for tag in card.find_all(["span", "p", "div", "td"]):
        text = tag.get_text(strip=True)
        if _LOCATION_KEYWORDS_RE.search(text) and len(text) < 200:
            if "·" in text:
                _, location = _parse_company_location(text)
                if location:
                    return _clean_location(location)
            return _clean_location(text)

    return None


def _extract_snippet_from_card(card: Tag, title: str) -> str:
    """Extract snippet from a card container.

    Supports both:
    - <p class="snippet"> element (older format)
    - Any substantial <p> that isn't the title or company·location line
    """
    # Method 0: Explicit <p class="snippet"> element (older format)
    snippet_p = card.find("p", class_="snippet")
    if snippet_p:
        return _truncate_snippet(snippet_p.get_text(strip=True))

    # Method 1: Look for longer text blocks that aren't the title
    for p in card.find_all("p"):
        text = p.get_text(strip=True)
        if text and text != title and len(text) > 20:
            # Skip company · location lines
            if "·" in text and len(text) < 100:
                continue
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

    # Group links by job ID to deduplicate (LinkedIn emails have multiple
    # links per job: image link, title link, CTA link)
    seen_job_ids: dict[str, JobCard] = {}

    for link in links:
        try:
            url = link["href"]
            title = _extract_title_from_link(link)

            # Skip empty-title links (image/icon links)
            if not title:
                continue

            # Find the card container for this link
            card = _extract_card_from_link(link)

            # Extract fields from the card
            company = _extract_company_from_card(card, title)
            location = _extract_location_from_card(card)
            snippet = _extract_snippet_from_card(card, title)

            # Clean up title - remove trailing company+location if concatenated
            # LinkedIn format: "TitleCompany · LocationStatus" where Company · Location
            # comes from a sibling <p>, and Status is "Actively recruiting", "23 connections", etc.
            clean_title = title
            if "·" in clean_title:
                parts = _COMPANY_LOCATION_SPLIT.split(clean_title, maxsplit=1)
                left = parts[0].strip()
                right = parts[1].strip() if len(parts) > 1 else ""

                if right and not location and _LOCATION_KEYWORDS_RE.search(right):
                    location = _clean_location(right)

                if company and company != "Unknown" and left.endswith(company) and len(left) > len(company):
                    clean_title = left[: -len(company)].strip()
                else:
                    clean_title = left
            elif company and company != "Unknown" and clean_title.endswith(company) and len(clean_title) > len(company):
                idx = len(clean_title) - len(company)
                if not clean_title[idx - 1].isspace() and clean_title[idx - 1] not in ("-", "–", "—", ":", ",", "("):
                    clean_title = clean_title[:idx].strip()

            # Deduplicate by job ID
            job_id = _extract_job_id(url)
            if job_id and job_id in seen_job_ids:
                existing = seen_job_ids[job_id]
                if (
                    clean_title
                    and clean_title.lower() not in _CTA_TEXTS
                    and len(clean_title) < len(existing.title)
                ):
                    existing.title = clean_title
                if existing.company == "Unknown" and company != "Unknown":
                    existing.company = company
                if existing.location is None and location is not None:
                    existing.location = location
                if not existing.snippet and snippet:
                    existing.snippet = snippet
                continue

            card_data = JobCard(
                title=clean_title,
                company=company,
                location=location,
                url=url,
                snippet=snippet,
                source_email_id=source_email_id,
                source_date=source_date,
            )

            if job_id:
                seen_job_ids[job_id] = card_data
            else:
                # No job ID in URL (search link), deduplicate by URL
                if not any(c.url == url for c in seen_job_ids.values()):
                    seen_job_ids[f"_url_{url}"] = card_data

        except Exception:
            logger.warning(
                "Failed to extract job card from link in email %s",
                source_email_id,
                exc_info=True,
            )
            continue

    return list(seen_job_ids.values())