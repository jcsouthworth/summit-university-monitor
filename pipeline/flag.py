"""
pipeline/flag.py

Auto-flagging — marks items as "Needs Attention" based on keyword matches.
Sets item["flagged"] = True and item["flag_reasons"] = [list of matched keywords].
"""

import re
import logging

logger = logging.getLogger(__name__)


def apply(items: list[dict], config: dict) -> list[dict]:
    """Mutate items in place, adding flagged and flag_reasons fields."""
    keywords: list[str] = config.get("flag_keywords", [])

    if not keywords:
        for item in items:
            item["flagged"] = False
            item["flag_reasons"] = []
        return items

    # Build one pattern per keyword for readable match reporting
    compiled = [(kw, re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)) for kw in keywords]

    flagged_count = 0
    for item in items:
        searchable = " ".join([
            item.get("title", ""),
            item.get("description", ""),
            item.get("address", ""),
        ])
        reasons = [kw for kw, pat in compiled if pat.search(searchable)]
        item["flagged"] = bool(reasons)
        item["flag_reasons"] = reasons
        if reasons:
            flagged_count += 1
            logger.debug("Flagged '%s' for: %s", item.get("title", "")[:60], reasons)

    logger.info("Flagging: %d of %d items flagged", flagged_count, len(items))
    return items
