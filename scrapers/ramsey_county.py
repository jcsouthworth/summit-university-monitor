"""
Scraper: Ramsey County — Board Agendas & Road Projects
Source: ramseycounty.us (HTML scraping)

Fetches county board meeting agendas and public works road project listings.
"""

import logging
import re
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; SUPC-NeighborhoodMonitor/1.0; "
        "+https://github.com/summituniversityplanningcouncil/neighborhood-monitor)"
    )
}


def fetch(config: dict) -> list[dict]:
    cfg = config["sources"]["ramsey_county"]
    if not cfg.get("enabled", True):
        return []

    items = []
    items.extend(_scrape_board_agendas(cfg))
    items.extend(_scrape_road_projects(cfg))
    logger.info("Ramsey County: fetched %d items total", len(items))
    return items


# ── County Board Agendas ──────────────────────────────────────────────────────

def _scrape_board_agendas(cfg: dict) -> list[dict]:
    url = cfg["board_url"]
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error("Ramsey County board page error: %s", e)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    items = []

    for link in soup.find_all("a", href=True):
        href = link["href"]
        text = link.get_text(strip=True)
        text_l = text.lower()
        href_l = href.lower()

        if not any(w in text_l or w in href_l for w in ["agenda", "minutes", "board", "meeting"]):
            continue
        if len(text) < 4:
            continue

        date_str = _extract_date(text) or _extract_date_from_context(link)
        title = f"Ramsey County Board — {date_str or 'Upcoming'}"

        items.append({
            "title": title,
            "description": (
                f"Ramsey County Board of Commissioners meeting. "
                f"Review agenda for items affecting Saint Paul neighborhoods. Link: {text}"
            ),
            "date": date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "source": cfg.get("label", "Ramsey County"),
            "source_key": "ramsey_county",
            "category": "hearing",
            "address": "",
            "url": _abs(href, url),
            "raw": {"link_text": text, "href": href},
        })

    # Deduplicate by URL
    seen = set()
    deduped = []
    for item in items:
        if item["url"] not in seen:
            seen.add(item["url"])
            deduped.append(item)

    logger.info("Ramsey County board agendas: %d items", len(deduped))
    return deduped


# ── Road Projects ─────────────────────────────────────────────────────────────

def _scrape_road_projects(cfg: dict) -> list[dict]:
    url = cfg["roads_url"]
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error("Ramsey County roads page error: %s", e)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    items = []

    # Road project pages typically list projects with headings or cards
    # Strategy: collect all distinct linked project pages or named project blocks
    project_blocks = (
        soup.find_all("article")
        or soup.find_all("div", class_=re.compile(r"project|card|item", re.I))
        or []
    )

    if project_blocks:
        for block in project_blocks:
            item = _parse_project_block(block, url, cfg)
            if item:
                items.append(item)
    else:
        # Fallback: grab all links on the page that look like project links
        for link in soup.find_all("a", href=True):
            href = link["href"]
            text = link.get_text(strip=True)
            if not text or len(text) < 10:
                continue
            road_words = ["project", "construction", "resurfac", "reconstruct", "utility", "trail"]
            if not any(w in text.lower() or w in href.lower() for w in road_words):
                continue
            items.append({
                "title": f"Ramsey County Road Project — {text[:80]}",
                "description": text[:300],
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "source": cfg.get("label", "Ramsey County"),
                "source_key": "ramsey_county",
                "category": "road",
                "address": _extract_address(text),
                "url": _abs(href, url),
                "raw": {"link_text": text, "href": href},
            })

    logger.info("Ramsey County road projects: %d items", len(items))
    return items


def _parse_project_block(block, base_url: str, cfg: dict) -> dict | None:
    heading = block.find(re.compile(r"h[2-6]|strong"))
    if not heading:
        return None
    title_text = heading.get_text(strip=True)
    if not title_text:
        return None

    desc_tag = block.find("p")
    description = desc_tag.get_text(strip=True)[:300] if desc_tag else title_text

    link = block.find("a", href=True)
    url = _abs(link["href"], base_url) if link else base_url

    date_str = _extract_date(block.get_text())

    return {
        "title": f"Road Project — {title_text[:80]}",
        "description": description,
        "date": date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "source": cfg.get("label", "Ramsey County"),
        "source_key": "ramsey_county",
        "category": "road",
        "address": _extract_address(title_text + " " + description),
        "url": url,
        "raw": {"block_text": block.get_text(strip=True)[:300]},
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_date(text: str) -> str | None:
    patterns = [
        (r"(\w+ \d{1,2},?\s*\d{4})", ["%B %d %Y", "%B %d, %Y", "%b %d %Y", "%b %d, %Y"]),
        (r"(\d{1,2}/\d{1,2}/\d{4})", ["%m/%d/%Y"]),
        (r"(\d{4}-\d{2}-\d{2})", ["%Y-%m-%d"]),
    ]
    for pat, fmts in patterns:
        m = re.search(pat, text)
        if m:
            raw = m.group(1).strip().rstrip(",")
            for fmt in fmts:
                try:
                    return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
                except ValueError:
                    continue
    return None


def _extract_date_from_context(tag) -> str | None:
    for parent in tag.parents:
        if parent.name in ("li", "div", "section", "article", "tr", "td"):
            text = parent.get_text()
            date = _extract_date(text)
            if date:
                return date
        if parent.name == "body":
            break
    return None


def _extract_address(text: str) -> str:
    # Look for a street number + street name pattern
    m = re.search(r"\b\d{2,5}\s+[A-Za-z][A-Za-z\s]+(Ave|St|Blvd|Dr|Rd|Pkwy|Ln|Way|Ct)\b", text)
    return m.group(0) if m else ""


def _abs(href: str, base: str) -> str:
    if href.startswith("http"):
        return href
    return urljoin(base, href)
