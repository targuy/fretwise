"""Run fretwise.quality.assess_source_quality on every GP file in partitions/.

Aggregates clean / suspect / bad verdict counts and lists the most
suspicious files. Output goes to docs/benchmarks/quality_scan_corpus.txt.

Useful for:
  - FretWise: filter audits on quality.is_clean for unbiased baselines
  - GuitarDataSet: exclude bad-quality files from ML training
"""
from __future__ import annotations

import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from fretwise.parser import get_adapter
from fretwise.quality import assess_source_quality


def main() -> None:
    corpus = Path(sys.argv[1] if len(sys.argv) > 1 else "partitions")
    files = sorted(corpus.glob("*.gp*"))
    print(f"Scanning {len(files)} files in {corpus}")

    verdicts: Counter[str] = Counter()
    by_file: list[tuple[str, str, str, int]] = []
    parse_fail = 0
    no_events = 0
    t0 = time.time()

    for i, path in enumerate(files):
        if i > 0 and i % 200 == 0:
            print(f"  [{i}/{len(files)}]  elapsed={time.time()-t0:.0f}s", flush=True)
        try:
            adapter = get_adapter(path)
            events = adapter.parse(path)
        except Exception:
            parse_fail += 1
            continue
        if not events:
            no_events += 1
            continue
        report = assess_source_quality(events)
        verdicts[report.verdict] += 1
        by_file.append((path.name, report.verdict, report.rationale, report.note_count))

    elapsed = time.time() - t0
    print(f"\nScan complete in {elapsed:.0f}s")
    print(f"  parse_fail: {parse_fail}")
    print(f"  no_events:  {no_events}")
    for v in ("clean", "suspect", "bad"):
        print(f"  {v}: {verdicts[v]} ({100*verdicts[v]/max(sum(verdicts.values()),1):.1f}%)")

    print(f"\n=== Bad files ({verdicts['bad']}) ===")
    for name, verdict, rationale, n in by_file:
        if verdict == "bad":
            print(f"  [{n:>5}n] {name}: {rationale}")

    print(f"\n=== Top suspect files (first 20) ===")
    suspect = [t for t in by_file if t[1] == "suspect"]
    for name, _, rationale, n in suspect[:20]:
        print(f"  [{n:>5}n] {name}: {rationale}")
    if len(suspect) > 20:
        print(f"  ... and {len(suspect)-20} more")


if __name__ == "__main__":
    main()
