#!/usr/bin/env python3
"""
run.py — SUPC Neighborhood Monitor main entry point

Usage:
    python run.py                # full run (fetch, filter, flag, generate)
    python run.py --dry-run      # print item count without writing HTML
    python run.py --source stpaul_permits   # run only one scraper
    python run.py --no-filter    # skip geographic filter (show all fetched items)
"""

import argparse
import logging
import sys
from pathlib import Path

import yaml

from scrapers import stpaul_permits, stpaul_planning, ramsey_county, mndot
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
    "stpaul_permits":  stpaul_permits.fetch,
    "stpaul_planning": stpaul_planning.fetch,
    "ramsey_county":   ramsey_county.fetch,
    "mndot":           mndot.fetch,
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
        "--source", metavar="NAME",
        choices=list(SCRAPERS.keys()),
        help="Run only a single scraper (for testing)",
    )
    parser.add_argument(
        "--no-filter", action="store_true",
        help="Skip geographic filter — show all fetched items",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug-level logging",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Load config
    config = load_config()
    logger.info("Config loaded — %d target ZIP codes, %d flag keywords",
                len(config.get("zip_codes", [])),
                len(config.get("flag_keywords", [])))

    # ── Step 1: Fetch ─────────────────────────────────────────────────────────
    all_items: list[dict] = []
    scrapers_to_run = {args.source: SCRAPERS[args.source]} if args.source else SCRAPERS

    for name, fetch_fn in scrapers_to_run.items():
        logger.info("Running scraper: %s", name)
        try:
            items = fetch_fn(config)
            logger.info("  → %d items from %s", len(items), name)
            all_items.extend(items)
        except Exception as e:
            logger.error("Scraper %s failed: %s", name, e, exc_info=args.verbose)
            # Continue — don't let one failed scraper break the whole run

    logger.info("Total fetched: %d items across all sources", len(all_items))

    if not all_items:
        logger.warning("No items fetched — dashboard will be empty")

    # ── Step 2: Deduplicate by URL + title ────────────────────────────────────
    seen: set[str] = set()
    deduped: list[dict] = []
    for item in all_items:
        key = (item.get("url", ""), item.get("title", ""))
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    logger.info("After dedup: %d items", len(deduped))

    # ── Step 3: Geographic filter ─────────────────────────────────────────────
    if args.no_filter:
        filtered = deduped
        logger.info("Geographic filter skipped (--no-filter)")
    else:
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
