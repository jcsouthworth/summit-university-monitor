"""
pipeline/filter.py

Geographic filter — keeps only items that are plausibly within or adjacent
to the target neighborhoods.

Filtering strategy by source:
  - stpaul_permits:  trusted (ZIP-filtered at the Socrata API query level)
  - stpaul_planning: trusted (Saint Paul Planning Commission covers our city;
                     agenda links carry no per-item address to filter on)
  - ramsey_county:   trusted (county board and road pages are already scoped
                     to Ramsey County, which contains our neighborhoods)
  - mndot:           geo-filtered — MnDOT covers the whole state, so we check
                     for ZIP, neighborhood, corridor, or "Saint Paul" mentions

An item from mndot passes if ANY of the following match (case-insensitive):
  1. Its text contains one of the target ZIP codes
  2. Its text mentions a neighborhood name
  3. Its text mentions a target corridor / street name
  4. Its text mentions "Saint Paul" or "Ramsey"
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

    # 4. Source-level trust rules
    source_key = item.get("source_key", "")

    # Permit API: ZIP-filtered at query level — always relevant
    if source_key == "stpaul_permits":
        return True

    # Planning Commission and BZA: scoped to Saint Paul government —
    # agenda links carry no per-item address, so trust all items
    if source_key == "stpaul_planning":
        return True

    # Ramsey County: board agendas and road projects are county-scoped,
    # which fully contains our target neighborhoods — trust all items
    if source_key == "ramsey_county":
        return True

    # MnDOT / Metro Transit: statewide source — apply a broader Saint Paul
    # check in addition to the neighborhood/corridor patterns above
    if source_key == "mndot":
        saint_paul_pattern = re.compile(r"\bsaint paul\b|\bramsey\b", re.IGNORECASE)
        if saint_paul_pattern.search(searchable):
            return True
        # If none of the geo signals matched, drop it
        return False

    # Unknown source — apply full geo filter (already checked above)
    return False
