"""
Scraper: Saint Paul Planning Commission via Granicus
Source: https://stpaul.granicus.com/ViewPublisher.php?view_id=56

Strategy:
  1. Parse the Granicus RSS feed (agenda mode) — clean, structured, reliable.
     Gives us every meeting that has a published agenda, with date, title, and
     a direct link to the agenda PDF viewer.
  2. Scrape the HTML listing page to catch upcoming meetings whose agendas
     have not yet been published (they appear on the listing but not in the feed).

Returns one item per meeting.
"""

import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; SUPC-NeighborhoodMonitor/1.0; "
        "+https://github.com/jcsouthworth/summit-university-monitor)"
    )
}


def fetch(config: dict) -> list[dict]:
    cfg = config["sources"]["granicus"]
    if not cfg.get("enabled", True):
        return []

    items: list[dict] = []
    seen_clip_ids: set[str] = set()

    # ── 1. RSS feed ───────────────────────────────────────────────────────────
    rss_items = _fetch_rss(cfg)
    for item in rss_items:
        clip_id = _clip_id_from_url(item["url"])
        if clip_id:
            seen_clip_ids.add(clip_id)
        items.append(item)

    # ── 2. HTML listing page — upcoming meetings not yet in the RSS feed ──────
    html_items = _scrape_listing(cfg, seen_clip_ids)
    items.extend(html_items)

    logger.info("Granicus: %d total items (%d from RSS, %d from listing page)",
                len(items), len(rss_items), len(html_items))
    return items


# ── RSS feed ──────────────────────────────────────────────────────────────────

def _fetch_rss(cfg: dict) -> list[dict]:
    url = cfg["rss_url"]
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error("Granicus RSS error: %s", e)
        return []

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as e:
        logger.error("Granicus RSS parse error: %s", e)
        return []

    channel = root.find("channel")
    if channel is None:
        return []

    items = []
    for entry in channel.findall("item"):
        item = _parse_rss_item(entry, cfg)
        if item:
            items.append(item)

    logger.info("Granicus RSS: parsed %d items", len(items))
    return items


def _parse_rss_item(entry, cfg: dict) -> dict | None:
    title_el = entry.find("title")
    link_el  = entry.find("link")
    pub_el   = entry.find("pubDate")

    if title_el is None or not title_el.text:
        return None

    raw_title = title_el.text.strip()
    link = (link_el.text or "").strip() if link_el is not None else ""
    raw_pub = (pub_el.text or "").strip() if pub_el is not None else ""

    # Parse the meeting date out of the title ("Planning Commission Meeting - Feb 20, 2026")
    meeting_date = _date_from_title(raw_title) or _date_from_pubdate(raw_pub)

    canceled = "cancel" in raw_title.lower()
    special  = "special" in raw_title.lower()

    title = _format_title(raw_title, canceled, special)

    description_parts = ["Saint Paul Planning Commission meeting."]
    if canceled:
        description_parts.append("This meeting was canceled.")
    if link:
        description_parts.append("Agenda PDF available at the link.")

    return {
        "title": title,
        "description": " ".join(description_parts),
        "date": meeting_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "source": cfg.get("label", "Saint Paul Planning Commission"),
        "source_key": "granicus",
        "category": "hearing",
        "address": "",
        "url": link,
        "canceled": canceled,
        "special": special,
        "raw": {"rss_title": raw_title, "pub_date": raw_pub},
    }


# ── HTML listing page ─────────────────────────────────────────────────────────

def _scrape_listing(cfg: dict, already_seen: set[str]) -> list[dict]:
    """Scrape the main listing page for meetings not yet in the RSS feed."""
    url = cfg["listing_url"]
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error("Granicus listing page error: %s", e)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    items = []

    # Granicus listing tables use class "listingTable" with rows "listingRow"
    for row in soup.find_all("tr", class_=re.compile(r"listingRow", re.I)):
        item = _parse_listing_row(row, url, cfg, already_seen)
        if item:
            items.append(item)

    # Fallback: if no listingRow class, try plain <tr> inside a table
    if not items:
        for table in soup.find_all("table"):
            for row in table.find_all("tr"):
                item = _parse_listing_row(row, url, cfg, already_seen)
                if item:
                    items.append(item)

    logger.info("Granicus listing page: %d new items not in RSS", len(items))
    return items


def _parse_listing_row(row, base_url: str, cfg: dict, already_seen: set[str]) -> dict | None:
    # Look for an agenda link in this row
    agenda_link = None
    for a in row.find_all("a", href=True):
        href = a["href"]
        if "AgendaViewer" in href or "clip_id" in href:
            agenda_link = href
            break

    if not agenda_link:
        return None

    # Normalise the href (Granicus uses protocol-relative URLs like //stpaul.granicus.com/...)
    if agenda_link.startswith("//"):
        agenda_link = "https:" + agenda_link
    elif not agenda_link.startswith("http"):
        agenda_link = urljoin(base_url, agenda_link)

    # Skip if we already have this meeting from the RSS feed
    clip_id = _clip_id_from_url(agenda_link)
    if clip_id and clip_id in already_seen:
        return None

    # Extract date / title from row text
    row_text = row.get_text(separator=" ", strip=True)
    meeting_date = _date_from_text(row_text)
    canceled = "cancel" in row_text.lower()
    special  = "special" in row_text.lower()

    raw_title = f"Planning Commission Meeting — {meeting_date or 'Upcoming'}"
    title = _format_title(raw_title, canceled, special)

    return {
        "title": title,
        "description": "Saint Paul Planning Commission upcoming meeting. Agenda link available.",
        "date": meeting_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "source": cfg.get("label", "Saint Paul Planning Commission"),
        "source_key": "granicus",
        "category": "hearing",
        "address": "",
        "url": agenda_link,
        "canceled": canceled,
        "special": special,
        "raw": {"row_text": row_text[:200]},
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_title(raw: str, canceled: bool, special: bool) -> str:
    """Build a clean display title."""
    # Extract the date portion if present (e.g. "Feb 20, 2026")
    date_match = re.search(
        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2},?\s*\d{4}",
        raw, re.IGNORECASE
    )
    date_part = date_match.group(0) if date_match else None

    if date_part:
        base = f"Planning Commission — {date_part}"
    else:
        base = "Planning Commission Meeting"

    if canceled:
        base = f"[CANCELED] {base}"
    elif special:
        base = f"[SPECIAL] {base}"

    return base


def _date_from_title(title: str) -> str | None:
    """Extract a YYYY-MM-DD date from a Granicus meeting title string."""
    return _date_from_text(title)


def _date_from_pubdate(raw: str) -> str | None:
    """Parse an RFC 2822 pubDate string (e.g. 'Fri, 06 Feb 2026 06:30:00 -0800')."""
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return None


def _date_from_text(text: str) -> str | None:
    """Try several date patterns found in Granicus titles and row text."""
    patterns = [
        # "Feb 20, 2026" or "February 20, 2026"
        (r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\.?\s+\d{1,2},?\s*\d{4})",
         ["%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y", "%b. %d, %Y"]),
        # "20 February 2026"
        (r"(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})",
         ["%d %B %Y"]),
        # ISO "2026-02-20"
        (r"(\d{4}-\d{2}-\d{2})",
         ["%Y-%m-%d"]),
        # "MM/DD/YYYY"
        (r"(\d{1,2}/\d{1,2}/\d{4})",
         ["%m/%d/%Y"]),
    ]
    for pat, fmts in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            raw = m.group(1).strip().rstrip(",")
            for fmt in fmts:
                try:
                    return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
                except ValueError:
                    continue
    return None


def _clip_id_from_url(url: str) -> str | None:
    """Extract the clip_id parameter from a Granicus URL."""
    m = re.search(r"clip_id=(\d+)", url)
    return m.group(1) if m else None
