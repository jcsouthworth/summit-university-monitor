"""
Scraper: City of Saint Paul — DSI Building Permits
Source: data.stpaul.gov (Socrata open data API)

Returns permit records filtered to the target ZIP codes.
Each record is a standardized item dict consumed by the pipeline.
"""

import logging
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

CATEGORY = "permit"
SOURCE_URL_BASE = "https://data.stpaul.gov/d/{dataset_id}"


def fetch(config: dict) -> list[dict]:
    """Fetch building permits from the Saint Paul Open Data Socrata API."""
    cfg = config["sources"]["stpaul_permits"]
    if not cfg.get("enabled", True):
        return []

    zip_codes = config["zip_codes"]
    dataset_id = cfg["dataset_id"]
    base_url = cfg["base_url"]
    limit = cfg.get("limit", 500)

    zip_field = cfg["zip_field"]
    date_field = cfg["date_field"]
    address_field = cfg["address_field"]
    type_field = cfg["type_field"]

    # Build Socrata SoQL query — filter to target ZIP codes
    zip_list = ", ".join(f"'{z}'" for z in zip_codes)
    params = {
        "$where": f"{zip_field} in ({zip_list})",
        "$order": f"{date_field} DESC",
        "$limit": limit,
    }

    url = f"{base_url}/{dataset_id}.json"
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error("Saint Paul permits API error: %s", e)
        return []

    records = resp.json()
    items = []
    for r in records:
        try:
            item = _normalize(r, cfg, dataset_id)
            if item:
                items.append(item)
        except Exception as e:
            logger.warning("Skipping permit record due to error: %s", e)

    logger.info("Saint Paul permits: fetched %d items", len(items))
    return items


def _normalize(record: dict, cfg: dict, dataset_id: str) -> dict | None:
    address_field = cfg["address_field"]
    date_field = cfg["date_field"]
    type_field = cfg["type_field"]

    address = record.get(address_field, "").strip()
    permit_type = record.get(type_field, "").strip()
    raw_date = record.get(date_field, "")
    permit_num = record.get("permit_number") or record.get("permit_no") or record.get("id", "")

    if not address and not permit_type:
        return None

    # Parse date — Socrata returns ISO 8601
    date_str = _parse_date(raw_date)

    # Build a link to the dataset record page (best we can do without a direct record URL)
    source_url = SOURCE_URL_BASE.format(dataset_id=dataset_id)

    title = f"{permit_type or 'Permit'} — {address or 'Address unknown'}"
    if permit_num:
        title += f" (#{permit_num})"

    description_parts = []
    for field in ["work_description", "contractor_name", "owner_name", "status"]:
        val = record.get(field, "").strip()
        if val:
            description_parts.append(f"{field.replace('_', ' ').title()}: {val}")

    return {
        "title": title,
        "description": " | ".join(description_parts) if description_parts else permit_type,
        "date": date_str,
        "source": cfg.get("label", "Saint Paul DSI"),
        "source_key": "stpaul_permits",
        "category": CATEGORY,
        "address": address,
        "url": source_url,
        "raw": record,
    }


def _parse_date(raw: str) -> str:
    if not raw:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # Socrata returns "2024-01-15T00:00:00.000" or similar
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw[:19], fmt[:len(fmt)]).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return raw[:10] if len(raw) >= 10 else raw
