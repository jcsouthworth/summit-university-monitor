"""
Scraper: City of Saint Paul — Legistar Calendar
Source: https://stpaul.legistar.com/Calendar.aspx

Legistar is Saint Paul's municipal meeting management system. The calendar
page lists upcoming meetings for all city bodies: City Council, HRA, Library
Board, committees, licensing hearings, etc.

The page renders a Telerik RadGrid table — standard HTML, no JavaScript
rendering required for the initial load.
"""

import logging
import re
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://stpaul.legistar.com/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; SUPC-NeighborhoodMonitor/1.0; "
        "+https://github.com/jcsouthworth/summit-university-monitor)"
    )
}


def fetch(config: dict) -> list[dict]:
    cfg = config["sources"]["legistar"]
    if not cfg.get("enabled", True):
        return []

    url = cfg["calendar_url"]
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error("Legistar calendar error: %s", e)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # The calendar data lives in a RadGrid table
    table = soup.find("table", id=re.compile(r"gridCalendar", re.I))
    if not table:
        # Fallback: find any table that looks like a meeting calendar
        for t in soup.find_all("table"):
            headers = [th.get_text(strip=True).lower() for th in t.find_all("th")]
            if any("date" in h or "meeting" in h or "name" in h for h in headers):
                table = t
                break

    if not table:
        logger.error("Legistar: could not find calendar table in page")
        return []

    # Parse column positions from header row
    col_map = _parse_column_map(table)
    logger.debug("Legistar column map: %s", col_map)

    items = []
    for row in table.find_all("tr"):
        # Skip header rows
        if row.find("th"):
            continue
        item = _parse_row(row, col_map, cfg)
        if item:
            items.append(item)

    logger.info("Legistar: parsed %d items", len(items))
    return items


# ── Parsing helpers ───────────────────────────────────────────────────────────

def _parse_column_map(table) -> dict[str, int]:
    """Map column names to their index positions from the header row."""
    col_map = {}
    header_row = table.find("tr")
    if not header_row:
        return col_map
    for i, th in enumerate(header_row.find_all(["th", "td"])):
        text = th.get_text(strip=True).lower()
        if "name" in text:
            col_map.setdefault("name", i)
        elif "date" in text:
            col_map.setdefault("date", i)
        elif "time" in text:
            col_map.setdefault("time", i)
        elif "location" in text:
            col_map.setdefault("location", i)
        elif "agenda" in text:
            col_map.setdefault("agenda", i)
        elif "minutes" in text:
            col_map.setdefault("minutes", i)
        elif "detail" in text:
            col_map.setdefault("details", i)
    return col_map


def _parse_row(row, col_map: dict, cfg: dict) -> dict | None:
    cells = row.find_all("td")
    if not cells or len(cells) < 2:
        return None

    def cell_text(key: str, fallback: int = -1) -> str:
        idx = col_map.get(key, fallback)
        if idx < 0 or idx >= len(cells):
            return ""
        return cells[idx].get_text(strip=True)

    def cell_link(key: str, fallback: int = -1) -> str:
        idx = col_map.get(key, fallback)
        if idx < 0 or idx >= len(cells):
            return ""
        a = cells[idx].find("a", href=True)
        if a:
            href = a["href"]
            return href if href.startswith("http") else urljoin(BASE_URL, href)
        return ""

    name     = cell_text("name",     0)
    date_raw = cell_text("date",     1)
    time_raw = cell_text("time",     2)
    location = cell_text("location", 3)

    if not name or not date_raw:
        return None

    # Parse date
    date_str = _parse_date(date_raw)
    if not date_str:
        logger.debug("Legistar: could not parse date '%s' for '%s'", date_raw, name)
        return None

    # Prefer agenda link; fall back to details link; fall back to calendar page
    agenda_url = cell_link("agenda") or cell_link("details") or cfg["calendar_url"]

    # Build description
    desc_parts = [f"Meeting body: {name}"]
    if time_raw:
        desc_parts.append(f"Time: {time_raw}")
    if location:
        desc_parts.append(f"Location: {location}")

    title = f"{name} — {date_raw}"
    if time_raw:
        title += f" at {time_raw}"

    return {
        "title": title,
        "description": " | ".join(desc_parts),
        "date": date_str,
        "source": cfg.get("label", "Saint Paul Legistar"),
        "source_key": "legistar",
        "category": "hearing",
        "address": location,
        "url": agenda_url,
        "raw": {
            "name": name,
            "date": date_raw,
            "time": time_raw,
            "location": location,
        },
    }


def _parse_date(raw: str) -> str | None:
    """Parse Legistar date strings like '3/4/2026' or 'March 4, 2026'."""
    raw = raw.strip()
    formats = [
        "%m/%d/%Y",       # 3/4/2026
        "%B %d, %Y",      # March 4, 2026
        "%b %d, %Y",      # Mar 4, 2026
        "%Y-%m-%d",       # 2026-03-04
    ]
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None
