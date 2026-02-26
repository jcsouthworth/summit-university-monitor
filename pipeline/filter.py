"""
pipeline/filter.py

Filtering strategy by source:

  legistar  — Geographic filtering is applied inside the scraper itself,
               on individual agenda items. Items arriving here are already
               geo-relevant. Pass through.

  granicus  — Planning Commission meeting-level items. Already scoped to
               Saint Paul Planning Commission. Pass through.

This module is kept as a named pipeline stage so the overall flow stays
consistent and additional filtering can be added here without touching
the scrapers.
"""

import logging

logger = logging.getLogger(__name__)


def apply(items: list[dict], config: dict) -> list[dict]:
    logger.info("Filter: %d items passed through", len(items))
    return items
