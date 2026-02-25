"""
pipeline/generate.py

Generates the static HTML dashboard from processed items using a Jinja2 template.
Writes output to docs/index.html (GitHub Pages root).
"""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
OUTPUT_DIR = Path(__file__).parent.parent / "docs"
OUTPUT_FILE = OUTPUT_DIR / "index.html"


def build(items: list[dict], config: dict) -> Path:
    """Render the dashboard and write to docs/index.html. Returns output path."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("dashboard.html")

    # Sort: flagged first, then by date descending
    sorted_items = sorted(
        items,
        key=lambda x: (not x.get("flagged", False), x.get("date", "") or ""),
        reverse=False,
    )
    # Within the sorted list, date should be newest-first within each flagged group
    flagged = sorted(
        [i for i in sorted_items if i.get("flagged")],
        key=lambda x: x.get("date", ""),
        reverse=True,
    )
    unflagged = sorted(
        [i for i in sorted_items if not i.get("flagged")],
        key=lambda x: x.get("date", ""),
        reverse=True,
    )
    ordered_items = flagged + unflagged

    # Gather unique sources and categories for filter dropdowns
    sources = sorted({i.get("source", "") for i in ordered_items if i.get("source")})
    categories = sorted({i.get("category", "") for i in ordered_items if i.get("category")})

    # Stats
    stats = {
        "total": len(ordered_items),
        "flagged": len(flagged),
        "permits": sum(1 for i in ordered_items if i.get("category") == "permit"),
        "hearings": sum(1 for i in ordered_items if i.get("category") == "hearing"),
        "roads": sum(1 for i in ordered_items if i.get("category") == "road"),
        "funding": sum(1 for i in ordered_items if i.get("category") == "funding"),
    }

    now_utc = datetime.now(timezone.utc)
    rendered = template.render(
        items=ordered_items,
        sources=sources,
        categories=categories,
        stats=stats,
        config=config,
        last_updated=now_utc.strftime("%B %d, %Y at %I:%M %p UTC"),
        last_updated_iso=now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        dashboard=config.get("dashboard", {}),
    )

    OUTPUT_FILE.write_text(rendered, encoding="utf-8")
    logger.info("Dashboard written to %s (%d items)", OUTPUT_FILE, len(ordered_items))
    return OUTPUT_FILE
