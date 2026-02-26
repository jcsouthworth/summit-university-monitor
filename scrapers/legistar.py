"""
Scraper: City of Saint Paul — Legistar Web API
Source: https://webapi.legistar.com/v1/stpaul

Uses the Legistar REST API to fetch individual agenda items from all city
meetings (City Council, HRA, committees, boards, etc.), then applies a
geographic filter to keep only items relevant to Summit-University and
adjacent neighborhoods.

This returns one dashboard item per relevant agenda item — not one per
meeting — so the council sees specific actions like:
  "2026 Saint Anthony/Rondo Arterial Mill and Overlay Project final order"
rather than just a link to a full meeting agenda PDF.
"""

import logging
import re
import time
from datetime import datetime, timedelta, timezone

import requests

logger = logging.getLogger(__name__)

API_BASE = "https://webapi.legistar.com/v1/stpaul"
MEETING_DETAIL_URL = "https://stpaul.legistar.com/MeetingDetail.aspx?LEGID={event_id}&GID=125&G=EDAB5C5F-1041-4DF4-A894-59E957785E36"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; SUPC-NeighborhoodMonitor/1.0; "
        "+https://github.com/jcsouthworth/summit-university-monitor)"
    )
}

# Matter types that map to dashboard categories
MATTER_TYPE_CATEGORY = {
    "ordinance":        "hearing",
    "resolution":       "hearing",
    "resolution-ph":    "hearing",
    "public hearing":   "hearing",
    "resolution lh":    "hearing",
    "administrative order": "hearing",
    "contract":         "funding",
    "grant":            "funding",
    "road":             "road",
    "right of way":     "road",
}


def fetch(config: dict) -> list[dict]:
    cfg = config["sources"]["legistar"]
    if not cfg.get("enabled", True):
        return []

    geo = _build_geo_patterns(config)
    allowed_statuses = {s.lower() for s in cfg.get("agenda_statuses", ["Final", "Final-revised"])}

    # Date range
    today = datetime.now(timezone.utc).date()
    date_from = today - timedelta(days=cfg.get("lookback_days", 30))
    date_to   = today + timedelta(days=cfg.get("lookahead_days", 90))

    # ── Step 1: Fetch events in the date range ────────────────────────────────
    events = _fetch_events(cfg, date_from, date_to)
    logger.info("Legistar: %d events in date range %s → %s", len(events), date_from, date_to)

    # ── Step 2: For each event with a published agenda, fetch items ───────────
    all_items: list[dict] = []
    for event in events:
        agenda_status = (event.get("EventAgendaStatusName") or "").lower()
        if agenda_status not in allowed_statuses:
            logger.debug("Skipping event %s (%s) — agenda status: %s",
                         event.get("EventId"), event.get("EventBodyName"), agenda_status)
            continue

        event_id   = event["EventId"]
        body_name  = event.get("EventBodyName", "Saint Paul Legistar")
        event_date = _parse_event_date(event.get("EventDate", ""))
        meeting_url = event.get("EventInSiteURL") or MEETING_DETAIL_URL.format(event_id=event_id)

        items = _fetch_event_items(event_id)
        if items is None:
            # API error — skip this event but continue
            continue

        for raw_item in items:
            item = _process_item(raw_item, body_name, event_date, meeting_url, geo, cfg)
            if item:
                all_items.append(item)

        # Be polite to the API — small delay between per-event calls
        time.sleep(0.25)

    logger.info("Legistar: %d geo-relevant items across all events", len(all_items))
    return all_items


# ── API calls ─────────────────────────────────────────────────────────────────

def _fetch_events(cfg: dict, date_from, date_to) -> list[dict]:
    """Fetch all events in the given date range."""
    url = f"{API_BASE}/events"
    params = {
        "$filter": (
            f"EventDate ge datetime'{date_from.isoformat()}' and "
            f"EventDate le datetime'{date_to.isoformat()}'"
        ),
        "$orderby": "EventDate asc",
        "$top": 200,
    }
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        logger.error("Legistar events API error: %s", e)
        return []
    except ValueError as e:
        logger.error("Legistar events API JSON parse error: %s", e)
        return []


def _fetch_event_items(event_id: int) -> list[dict] | None:
    """Fetch individual agenda items for one event. Returns None on error."""
    url = f"{API_BASE}/events/{event_id}/eventitems"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        logger.error("Legistar event items API error (event %s): %s", event_id, e)
        return None
    except ValueError as e:
        logger.error("Legistar event items JSON parse error (event %s): %s", event_id, e)
        return None


# ── Item processing ───────────────────────────────────────────────────────────

def _process_item(
    raw: dict,
    body_name: str,
    event_date: str,
    meeting_url: str,
    geo,
    cfg: dict,
) -> dict | None:
    """
    Convert a raw Legistar event item into a dashboard item dict,
    or return None if the item should be skipped.
    """
    title        = (raw.get("EventItemTitle") or "").strip()
    matter_name  = (raw.get("EventItemMatterName") or "").strip()
    matter_file  = (raw.get("EventItemMatterFile") or "").strip()
    matter_type  = (raw.get("EventItemMatterType") or "").strip()
    matter_status = (raw.get("EventItemMatterStatus") or "").strip()
    agenda_num   = raw.get("EventItemAgendaNumber")

    # Skip structural rows (roll call, section headers, adjournment)
    if not title or not matter_type:
        return None

    # Skip generic filler items with no substantive content
    skip_titles = {"roll call", "adjournment", "communications & receive/file",
                   "approval of minutes", "public comment", "open forum"}
    if title.lower() in skip_titles:
        return None

    # ── Geographic filter ─────────────────────────────────────────────────────
    searchable = f"{title} {matter_name}"
    if not _geo_matches(searchable, geo):
        return None

    # ── Build dashboard item ──────────────────────────────────────────────────
    # Always link to the meeting page — LegislationDetail URLs use an internal
    # ID scheme that doesn't match the API's EventItemMatterId, so the meeting
    # page is the only reliable link. The full agenda is visible there.
    url = meeting_url

    # Build a clean display title
    display_title = matter_name or title
    if matter_file:
        display_title = f"{matter_file} — {display_title}"

    # Build description
    desc_parts = []
    if body_name:
        desc_parts.append(body_name)
    if matter_type:
        desc_parts.append(matter_type)
    if matter_status:
        desc_parts.append(matter_status)
    if agenda_num:
        desc_parts.append(f"Agenda item #{agenda_num}")
    description = " · ".join(desc_parts)

    category = _categorize(matter_type)

    return {
        "title": display_title[:200],
        "description": description,
        "date": event_date,
        "source": cfg.get("label", "Saint Paul Legistar"),
        "source_key": "legistar",
        "category": category,
        "address": _extract_address(searchable),
        "url": url,
        "raw": {
            "matter_file": matter_file,
            "matter_type": matter_type,
            "matter_status": matter_status,
            "body": body_name,
            "agenda_item": agenda_num,
        },
    }


# ── Geographic matching ───────────────────────────────────────────────────────

def _build_geo_patterns(config: dict) -> dict:
    """Pre-compile regex patterns for geographic filtering."""
    def make_pattern(terms):
        if not terms:
            return None
        return re.compile(
            r"\b(" + "|".join(re.escape(t) for t in terms) + r")\b",
            re.IGNORECASE,
        )

    return {
        "zip":          make_pattern(config.get("zip_codes", [])),
        "neighborhood": make_pattern(config.get("neighborhoods", [])),
        "corridor":     make_pattern(config.get("corridors", [])),
    }


def _geo_matches(text: str, geo: dict) -> bool:
    """Return True if the text mentions a target ZIP, neighborhood, or corridor.

    Normalizes street suffixes before matching so that government documents
    that spell out "Avenue", "Street", etc. match config entries like "Selby Ave".
    """
    normalized = _normalize_suffixes(text)
    for pattern in geo.values():
        if pattern and pattern.search(normalized):
            return True
    return False


# Suffix normalization map: full form → abbreviation used in config.yml corridors
_SUFFIX_MAP = [
    (re.compile(r"\bAvenue\b",   re.IGNORECASE), "Ave"),
    (re.compile(r"\bStreet\b",   re.IGNORECASE), "St"),
    (re.compile(r"\bBoulevard\b",re.IGNORECASE), "Blvd"),
    (re.compile(r"\bParkway\b",  re.IGNORECASE), "Pkwy"),
    (re.compile(r"\bDrive\b",    re.IGNORECASE), "Dr"),
    (re.compile(r"\bLane\b",     re.IGNORECASE), "Ln"),
    (re.compile(r"\bCourt\b",    re.IGNORECASE), "Ct"),
    (re.compile(r"\bCircle\b",   re.IGNORECASE), "Cir"),
    (re.compile(r"\bPlace\b",    re.IGNORECASE), "Pl"),
    (re.compile(r"\bRoad\b",     re.IGNORECASE), "Rd"),
]


def _normalize_suffixes(text: str) -> str:
    """Replace spelled-out street suffixes with standard abbreviations."""
    for pattern, replacement in _SUFFIX_MAP:
        text = pattern.sub(replacement, text)
    return text


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_event_date(raw: str) -> str:
    """Parse Legistar ISO date string '2026-01-28T00:00:00' → '2026-01-28'."""
    if not raw:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return raw[:10]


def _categorize(matter_type: str) -> str:
    """Map a Legistar matter type to a dashboard category."""
    if not matter_type:
        return "hearing"
    mt = matter_type.lower()
    for key, cat in MATTER_TYPE_CATEGORY.items():
        if key in mt:
            return cat
    return "hearing"


def _extract_address(text: str) -> str:
    """Pull a street address out of item text if present."""
    m = re.search(
        r"\b\d{2,5}\s+[A-Za-z][A-Za-z\s]+(Ave|St|Blvd|Dr|Rd|Pkwy|Ln|Way|Ct)\b",
        text, re.IGNORECASE,
    )
    return m.group(0) if m else ""
