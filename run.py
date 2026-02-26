#!/usr/bin/env python3
"""
run.py — SUPC Neighborhood Monitor main entry point

Usage:
    python run.py                # full run (fetch, filter, flag, generate)
    python run.py --dry-run      # print item count without writing HTML
    python run.py --verbose      # enable debug-level logging
"""

import argparse
import logging
import sys
from pathlib import Path

import yaml

from scrapers import granicus
from pipeline import filter as geo_filter, flag, generate

# ── Logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("run")

# ── Scraper registry ──────────────────────────────────────────────────────────
SCRAPERS = {
    "granicus": granicus.fetch,
}


def load_config() -> dict:
    config_path = Path(__file__).parent / "config.yml"
    with config_path.open() as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser(description="SUPC Neighborhood Monitor")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Fetch and process items but do not write the HTML dashboard",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug-level logging",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    config = load_config()
    logger.info("Config loaded — %d flag keywords", len(config.get("flag_keywords", [])))

    # ── Step 1: Fetch ─────────────────────────────────────────────────────────
    all_items: list[dict] = []
    for name, fetch_fn in SCRAPERS.items():
        logger.info("Running scraper: %s", name)
        try:
            items = fetch_fn(config)
            logger.info("  → %d items from %s", len(items), name)
            all_items.extend(items)
        except Exception as e:
            logger.error("Scraper %s failed: %s", name, e, exc_info=args.verbose)

    logger.info("Total fetched: %d items", len(all_items))

    # ── Step 2: Deduplicate by URL ────────────────────────────────────────────
    seen: set[str] = set()
    deduped: list[dict] = []
    for item in all_items:
        key = item.get("url", "") or item.get("title", "")
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    logger.info("After dedup: %d items", len(deduped))

    # ── Step 3: Filter ────────────────────────────────────────────────────────
    filtered = geo_filter.apply(deduped, config)

    # ── Step 4: Auto-flag ─────────────────────────────────────────────────────
    flagged_items = flag.apply(filtered, config)
    n_flagged = sum(1 for i in flagged_items if i.get("flagged"))
    logger.info("Flagged: %d of %d items", n_flagged, len(flagged_items))

    # ── Step 5: Generate dashboard ────────────────────────────────────────────
    if args.dry_run:
        logger.info("Dry run — skipping HTML generation")
        print(f"\nDry run complete:")
        print(f"  Fetched:  {len(all_items)}")
        print(f"  Filtered: {len(filtered)}")
        print(f"  Flagged:  {n_flagged}")
        return

    output_path = generate.build(flagged_items, config)
    logger.info("Dashboard generated: %s", output_path)
    print(f"\nDone. Dashboard written to: {output_path}")
    print(f"  Items: {len(flagged_items)}  |  Flagged: {n_flagged}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
