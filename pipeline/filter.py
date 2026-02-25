"""
pipeline/filter.py

Geographic filter — keeps only items that are plausibly within or adjacent
to the target neighborhoods.

An item passes if ANY of the following match (case-insensitive):
  1. Its address contains one of the target ZIP codes
  2. Its title or description mentions a neighborhood name
  3. Its title or description mentions a target corridor / street name
  4. Its address matches a corridor street name
"""

import re
import logging

logger = logging.getLogger(__name__)


def apply(items: list[dict], config: dict) -> list[dict]:
    """Return items that match the geographic scope defined in config."""
    zip_codes: list[str] = config.get("zip_codes", [])
    neighborhoods: list[str] = config.get("neighborhoods", [])
    corridors: list[str] = config.get("corridors", [])

    # Pre-compile patterns for efficiency
    zip_pattern = re.compile(
        r"\b(" + "|".join(re.escape(z) for z in zip_codes) + r")\b"
    ) if zip_codes else None

    neighborhood_pattern = re.compile(
        r"\b(" + "|".join(re.escape(n) for n in neighborhoods) + r")\b",
        re.IGNORECASE,
    ) if neighborhoods else None

    corridor_pattern = re.compile(
        r"\b(" + "|".join(re.escape(c) for c in corridors) + r")\b",
        re.IGNORECASE,
    ) if corridors else None

    passed = []
    dropped = 0
    for item in items:
        if _matches(item, zip_pattern, neighborhood_pattern, corridor_pattern):
            passed.append(item)
        else:
            dropped += 1
            logger.debug("Filtered out: %s", item.get("title", ""))

    logger.info(
        "Geographic filter: %d passed, %d dropped (total in: %d)",
        len(passed), dropped, len(items),
    )
    return passed


def _matches(
    item: dict,
    zip_pattern,
    neighborhood_pattern,
    corridor_pattern,
) -> bool:
    # Combine all text fields for searching
    searchable = " ".join([
        item.get("title", ""),
        item.get("description", ""),
        item.get("address", ""),
    ])

    # 1. ZIP code match
    if zip_pattern and zip_pattern.search(searchable):
        return True

    # 2. Neighborhood name match
    if neighborhood_pattern and neighborhood_pattern.search(searchable):
        return True

    # 3. Corridor / street name match
    if corridor_pattern and corridor_pattern.search(searchable):
        return True

    # 4. Permit/planning items from Saint Paul sources are pre-filtered by ZIP
    #    in the Socrata query, so pass them through if geo data is sparse
    source_key = item.get("source_key", "")
    if source_key == "stpaul_permits":
        # Already ZIP-filtered at API level — trust it
        return True

    return False
