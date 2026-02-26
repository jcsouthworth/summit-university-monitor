"""
pipeline/filter.py

For the Granicus scraper, all items come from Saint Paul's own Planning
Commission — they are already scoped to the right government body, so no
geographic filtering is needed. All items pass through.

This module is kept as a pass-through so the pipeline structure stays intact
and additional sources with geo-filtering can be added later.
"""

import logging

logger = logging.getLogger(__name__)


def apply(items: list[dict], config: dict) -> list[dict]:
    logger.info("Filter: passing all %d items through (single trusted source)", len(items))
    return items
