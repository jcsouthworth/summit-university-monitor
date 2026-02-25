"""
Scraper: MnDOT Metro District & Metro Transit — Active Projects
Source: dot.state.mn.us and metrotransit.org (HTML scraping)

Fetches active highway/infrastructure projects in the Metro area,
then geo-filters downstream to the target neighborhoods.
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
    cfg = config["sources"]["mndot"]
    if not cfg.get("enabled", True):
        return []

    items = []
    items.extend(_scrape_mndot_projects(cfg))
    items.extend(_scrape_metro_transit(cfg))
    logger.info("MnDOT/Metro: fetched %d items total", len(items))
    return items


# ── MnDOT Metro District Projects ────────────────────────────────────────────

def _scrape_mndot_projects(cfg: dict) -> list[dict]:
    url = cfg["projects_url"]
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error("MnDOT projects page error: %s", e)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    items = []

    # MnDOT project pages list projects as links or in tables
    # Strategy 1: look for table rows with project info
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        link = row.find("a", href=True)
        title_text = cells[0].get_text(strip=True) or (link.get_text(strip=True) if link else "")
        if not title_text or len(title_text) < 5:
            continue

        description = " | ".join(c.get_text(strip=True) for c in cells[1:])[:300]
        href = link["href"] if link else url

        items.append(_make_mndot_item(title_text, description, href, url, cfg))

    # Strategy 2: project links / cards
    if not items:
        for link in soup.find_all("a", href=True):
            href = link["href"]
            text = link.get_text(strip=True)
            if len(text) < 8:
                continue
            road_words = ["project", "construction", "highway", "interchange", "bridge",
                          "TH ", "MN-", "I-94", "I-35", "resurfac", "reconstruct"]
            if not any(w.lower() in text.lower() or w.lower() in href.lower() for w in road_words):
                continue
            items.append(_make_mndot_item(text, "", href, url, cfg))

    # Deduplicate by URL
    seen = set()
    deduped = []
    for item in items:
        if item["url"] not in seen:
            seen.add(item["url"])
            deduped.append(item)

    logger.info("MnDOT projects: %d items", len(deduped))
    return deduped


def _make_mndot_item(title: str, description: str, href: str, base_url: str, cfg: dict) -> dict:
    date_str = _extract_date(title + " " + description)
    return {
        "title": f"MnDOT Project — {title[:80]}",
        "description": description or title,
        "date": date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "source": cfg.get("label", "MnDOT / Metro"),
        "source_key": "mndot",
        "category": "road",
        "address": _extract_route_or_address(title + " " + description),
        "url": _abs(href, base_url),
        "raw": {"title": title, "description": description},
    }


# ── Metro Transit Capital Projects ────────────────────────────────────────────

def _scrape_metro_transit(cfg: dict) -> list[dict]:
    url = cfg["metro_transit_url"]
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error("Metro Transit projects page error: %s", e)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    items = []

    # Metro Transit project pages tend to use cards or list items
    project_containers = (
        soup.find_all("article")
        or soup.find_all("div", class_=re.compile(r"project|card|feature", re.I))
        or []
    )

    if project_containers:
        for block in project_containers:
            heading = block.find(re.compile(r"h[2-5]"))
            if not heading:
                continue
            title_text = heading.get_text(strip=True)
            desc_tag = block.find("p")
            description = desc_tag.get_text(strip=True)[:300] if desc_tag else ""
            link = block.find("a", href=True)
            href = link["href"] if link else url

            items.append({
                "title": f"Metro Transit — {title_text[:80]}",
                "description": description,
                "date": _extract_date(title_text + " " + description)
                        or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "source": cfg.get("label", "MnDOT / Metro"),
                "source_key": "mndot",
                "category": "road",
                "address": _extract_route_or_address(title_text + " " + description),
                "url": _abs(href, url),
                "raw": {"title": title_text, "description": description},
            })
    else:
        # Fallback: link scan
        for link in soup.find_all("a", href=True):
            text = link.get_text(strip=True)
            if len(text) < 10:
                continue
            transit_words = ["line", "corridor", "brt", "bus rapid", "light rail", "streetcar",
                             "station", "route", "extension", "transitway"]
            if not any(w in text.lower() for w in transit_words):
                continue
            items.append({
                "title": f"Metro Transit — {text[:80]}",
                "description": text,
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "source": cfg.get("label", "MnDOT / Metro"),
                "source_key": "mndot",
                "category": "road",
                "address": "",
                "url": _abs(link["href"], url),
                "raw": {"link_text": text},
            })

    logger.info("Metro Transit projects: %d items", len(items))
    return items


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_date(text: str) -> str | None:
    patterns = [
        (r"(\w+ \d{1,2},?\s*\d{4})", ["%B %d %Y", "%B %d, %Y", "%b %d %Y", "%b %d, %Y"]),
        (r"(\d{1,2}/\d{1,2}/\d{4})", ["%m/%d/%Y"]),
        (r"(\d{4}-\d{2}-\d{2})", ["%Y-%m-%d"]),
        (r"(\d{4})", ["%Y"]),  # year only — last resort
    ]
    for pat, fmts in patterns:
        m = re.search(pat, text)
        if m:
            raw = m.group(1).strip().rstrip(",")
            for fmt in fmts:
                try:
                    dt = datetime.strptime(raw, fmt)
                    # Don't return bare years in the far past/future
                    if fmt == "%Y" and not (2020 <= dt.year <= 2035):
                        continue
                    return dt.strftime("%Y-%m-%d")
                except ValueError:
                    continue
    return None


def _extract_route_or_address(text: str) -> str:
    # Highway designations
    for pat in [r"(I-\d+[A-Z]?)", r"(TH\s*\d+)", r"(MN-\d+)", r"(US-\d+)"]:
        m = re.search(pat, text, re.I)
        if m:
            return m.group(1)
    # Street address
    m = re.search(r"\b\d{2,5}\s+[A-Za-z][A-Za-z\s]+(Ave|St|Blvd|Dr|Rd|Pkwy|Ln|Way|Ct)\b", text)
    return m.group(0) if m else ""


def _abs(href: str, base: str) -> str:
    if href.startswith("http"):
        return href
    return urljoin(base, href)
