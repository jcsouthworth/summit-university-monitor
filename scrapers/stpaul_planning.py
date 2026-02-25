"""
Scraper: City of Saint Paul — Planning Commission & Board of Zoning Appeals
Source: stpaul.gov (HTML scraping)

Fetches upcoming meeting agendas and extracts hearing items.
"""

import logging
import re
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

CATEGORY_HEARING = "hearing"
SOURCE_LABEL = "Saint Paul Planning"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; SUPC-NeighborhoodMonitor/1.0; "
        "+https://github.com/summituniversityplanningcouncil/neighborhood-monitor)"
    )
}


def fetch(config: dict) -> list[dict]:
    cfg = config["sources"]["stpaul_planning"]
    if not cfg.get("enabled", True):
        return []

    items = []
    items.extend(_scrape_planning_commission(cfg))
    items.extend(_scrape_bza(cfg))
    logger.info("Saint Paul Planning: fetched %d items total", len(items))
    return items


# ── Planning Commission ──────────────────────────────────────────────────────

def _scrape_planning_commission(cfg: dict) -> list[dict]:
    url = cfg["meetings_url"]
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error("Planning Commission page error: %s", e)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    items = []

    # Look for meeting listings — typical pattern: <a> tags with "agenda" text
    # and date headings. The stpaul.gov site uses a common CMS structure.
    for link in soup.find_all("a", href=True):
        href = link["href"]
        text = link.get_text(strip=True)

        if not _is_agenda_link(text, href):
            continue

        # Try to extract a date from surrounding context or the link text
        date_str = _extract_date_from_text(text) or _extract_date_from_context(link)

        title = f"Planning Commission Agenda — {date_str or 'Upcoming'}"
        items.append({
            "title": title,
            "description": f"Saint Paul Planning Commission meeting agenda. Review for items in target neighborhoods.",
            "date": date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "source": SOURCE_LABEL,
            "source_key": "stpaul_planning",
            "category": CATEGORY_HEARING,
            "address": "",
            "url": _absolute_url(href, url),
            "raw": {"link_text": text, "href": href},
        })

    # Also look for any inline agenda items (case addresses listed on the page)
    items.extend(_extract_inline_cases(soup, url))

    # Deduplicate by URL
    seen = set()
    deduped = []
    for item in items:
        if item["url"] not in seen:
            seen.add(item["url"])
            deduped.append(item)

    logger.info("Planning Commission: found %d items", len(deduped))
    return deduped


def _scrape_bza(cfg: dict) -> list[dict]:
    url = cfg["bza_url"]
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error("BZA page error: %s", e)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    items = []

    for link in soup.find_all("a", href=True):
        href = link["href"]
        text = link.get_text(strip=True)
        if not _is_agenda_link(text, href):
            continue

        date_str = _extract_date_from_text(text) or _extract_date_from_context(link)
        title = f"Board of Zoning Appeals — {date_str or 'Upcoming'}"
        items.append({
            "title": title,
            "description": "Saint Paul Board of Zoning Appeals hearing. Review for variances and appeals in target neighborhoods.",
            "date": date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "source": SOURCE_LABEL,
            "source_key": "stpaul_planning",
            "category": CATEGORY_HEARING,
            "address": "",
            "url": _absolute_url(href, url),
            "raw": {"link_text": text, "href": href},
        })

    logger.info("BZA: found %d items", len(items))
    return items


# ── Helpers ──────────────────────────────────────────────────────────────────

def _is_agenda_link(text: str, href: str) -> bool:
    text_l = text.lower()
    href_l = href.lower()
    agenda_words = ["agenda", "minutes", "hearing", "meeting", "notice"]
    return any(w in text_l or w in href_l for w in agenda_words)


def _extract_date_from_text(text: str) -> str | None:
    """Try common date patterns found in government page link text."""
    patterns = [
        r"(\w+ \d{1,2},?\s*\d{4})",          # January 15, 2025
        r"(\d{1,2}/\d{1,2}/\d{2,4})",         # 1/15/2025
        r"(\d{4}-\d{2}-\d{2})",               # 2025-01-15
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return _normalize_date(m.group(1))
    return None


def _extract_date_from_context(tag) -> str | None:
    """Walk up the DOM to find a nearby date in a heading or parent element."""
    for parent in tag.parents:
        if parent.name in ("li", "div", "section", "article", "tr"):
            heading = parent.find(re.compile(r"h[2-6]|strong|b"))
            if heading:
                date = _extract_date_from_text(heading.get_text())
                if date:
                    return date
        if parent.name == "body":
            break
    return None


def _extract_inline_cases(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """Look for individual case/petition numbers listed inline on the page."""
    items = []
    # Pattern: "File #12-345-678" or "Case 12-345" or petition numbers
    case_pattern = re.compile(
        r"(file|case|petition|app(?:lication)?)[.\s#]*(\d[\d\-]+)",
        re.IGNORECASE,
    )
    for tag in soup.find_all(string=case_pattern):
        parent = tag.parent
        match = case_pattern.search(str(tag))
        if not match:
            continue
        case_num = match.group(2)
        full_text = parent.get_text(strip=True)[:200]
        date_str = _extract_date_from_text(full_text)
        link = parent.find("a", href=True)
        url = _absolute_url(link["href"], base_url) if link else base_url
        items.append({
            "title": f"Planning Case {case_num}",
            "description": full_text,
            "date": date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "source": SOURCE_LABEL,
            "source_key": "stpaul_planning",
            "category": CATEGORY_HEARING,
            "address": "",
            "url": url,
            "raw": {"case_num": case_num, "text": full_text},
        })
    return items


def _normalize_date(raw: str) -> str | None:
    raw = raw.strip().rstrip(",")
    formats = [
        "%B %d %Y", "%B %d, %Y", "%b %d %Y", "%b %d, %Y",
        "%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _absolute_url(href: str, base: str) -> str:
    if href.startswith("http"):
        return href
    from urllib.parse import urljoin
    return urljoin(base, href)
