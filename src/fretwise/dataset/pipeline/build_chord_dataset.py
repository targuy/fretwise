"""Build chord dataset from standard dictionary + scraped sources.

Usage:
    python scripts/build_chord_dataset.py              # standard dictionary only
    python scripts/build_chord_dataset.py --scrape      # also scrape online sources
"""
import logging
import sys

from fretwise.dataset.config import PROCESSED_DIR
from fretwise.dataset.data_schema.schema import save_chords
from fretwise.dataset.processors.validator import validate_chord
from fretwise.dataset.scrapers.chord_scraper import generate_standard_chords, scrape_chorddb_api

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main():
    do_scrape = "--scrape" in sys.argv

    # Phase 1: Standard dictionary (instant, no network)
    logger.info("Generating standard chord dictionary...")
    chords = generate_standard_chords()
    logger.info("Generated %d standard chord voicings", len(chords))

    # Phase 2: Scrape online sources (optional)
    if do_scrape:
        logger.info("Scraping online chord sources...")
        scraped = scrape_chorddb_api()
        chords.extend(scraped)
        logger.info("Total after scraping: %d voicings", len(chords))

    # Validate
    valid_chords = []
    invalid_count = 0
    for chord in chords:
        issues = validate_chord(chord)
        if issues:
            invalid_count += 1
            logger.debug("Invalid chord %s: %s", chord.name, issues)
        else:
            valid_chords.append(chord)

    logger.info("Validation: %d valid, %d invalid", len(valid_chords), invalid_count)

    # Deduplicate by (name, strings tuple)
    seen = set()
    unique_chords = []
    for c in valid_chords:
        key = (c.name, tuple(c.strings))
        if key not in seen:
            seen.add(key)
            unique_chords.append(c)

    logger.info("After dedup: %d unique voicings", len(unique_chords))

    # Save
    output = PROCESSED_DIR / "chord_dataset.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    save_chords(unique_chords, str(output))
    logger.info("Saved to %s", output)


if __name__ == "__main__":
    main()
