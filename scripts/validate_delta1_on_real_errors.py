"""Validate δ.1 prototype against the 762 detailed errors from GuitarDataSet.

For each error, compare:
- current `_natural_finger_assignment` output multiset (sorted frets_fretted)
- δ.1 alternative output multiset

Verdict per record:
- FIX:        δ.1 multiset gains gt_finger AND loses fw_finger vs current
- UNCHANGED:  δ.1 multiset == current multiset (δ.1 didn't fire or fired same way)
- DIFFERENT:  multisets differ but doesn't cleanly add gt / remove fw
- N/A:        n ∉ [3, 4] (δ.1 scope) or one of the algos returned None

Aggregated by n_fretted, error_type, and chord_name.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from fretwise.scoring import _natural_finger_assignment

# Re-import the prototype function
from prototype_delta1 import _alternative_finger_assignment  # noqa: E402

DETAILED_JSON = Path(
    "E:/DocumentsBenoit/pythonProject/handoff-FretWise-GuitarDataset/"
    "GuitarDataset-detailed-mr-errors.json"
)


def main() -> None:
    errors = json.loads(DETAILED_JSON.read_text(encoding="utf-8"))
    print(f"Loaded {len(errors)} errors\n")

    overall = Counter()
    by_n = defaultdict(Counter)
    by_type = defaultdict(Counter)
    by_chord_root = defaultdict(Counter)

    fix_examples = []
    regression_examples = []

    for err in errors:
        n = len(err["frets_fretted"])
        sorted_frets = sorted(err["frets_fretted"])
        et = err["error_type"]
        chord_root = err["chord_name"].rstrip("0123456789").split("/")[0]
        gt_f = err["gt_finger"]
        fw_f = err["fw_finger"]

        if n < 3 or n > 4:
            overall["NA_scope"] += 1
            by_n[n]["NA_scope"] += 1
            by_type[et]["NA_scope"] += 1
            continue

        cur = _natural_finger_assignment(sorted_frets)
        alt = _alternative_finger_assignment(sorted_frets)

        if cur is None or alt is None:
            overall["NA_invalid"] += 1
            by_n[n]["NA_invalid"] += 1
            by_type[et]["NA_invalid"] += 1
            continue

        cur_ms = Counter(f.name for f in cur)
        alt_ms = Counter(f.name for f in alt)

        if cur_ms == alt_ms:
            overall["UNCHANGED"] += 1
            by_n[n]["UNCHANGED"] += 1
            by_type[et]["UNCHANGED"] += 1
            by_chord_root[chord_root]["UNCHANGED"] += 1
            continue

        gain_gt = alt_ms.get(gt_f, 0) - cur_ms.get(gt_f, 0)
        lose_fw = cur_ms.get(fw_f, 0) - alt_ms.get(fw_f, 0)

        if gain_gt > 0 and lose_fw > 0:
            overall["FIX"] += 1
            by_n[n]["FIX"] += 1
            by_type[et]["FIX"] += 1
            by_chord_root[chord_root]["FIX"] += 1
            if len(fix_examples) < 5:
                fix_examples.append({
                    "chord": err["chord_name"], "frets": sorted_frets,
                    "cur": [f.name for f in cur], "alt": [f.name for f in alt],
                    "gt": gt_f, "fw": fw_f, "type": et,
                })
        elif gain_gt < 0 or (gain_gt == 0 and alt_ms.get(fw_f, 0) > cur_ms.get(fw_f, 0)):
            overall["REGRESSION"] += 1
            by_n[n]["REGRESSION"] += 1
            by_type[et]["REGRESSION"] += 1
            by_chord_root[chord_root]["REGRESSION"] += 1
            if len(regression_examples) < 5:
                regression_examples.append({
                    "chord": err["chord_name"], "frets": sorted_frets,
                    "cur": [f.name for f in cur], "alt": [f.name for f in alt],
                    "gt": gt_f, "fw": fw_f, "type": et,
                })
        else:
            overall["DIFFERENT"] += 1
            by_n[n]["DIFFERENT"] += 1
            by_type[et]["DIFFERENT"] += 1
            by_chord_root[chord_root]["DIFFERENT"] += 1

    print("=== Overall ===")
    total_in_scope = sum(v for k, v in overall.items() if not k.startswith("NA"))
    for cat in ("FIX", "UNCHANGED", "DIFFERENT", "REGRESSION", "NA_scope", "NA_invalid"):
        n = overall.get(cat, 0)
        pct_in_scope = 100 * n / total_in_scope if (total_in_scope and not cat.startswith("NA")) else None
        marker = f"  ({pct_in_scope:.1f}% of in-scope)" if pct_in_scope is not None else ""
        print(f"  {cat:<12} {n:>5}{marker}")

    print(f"\n  In-scope total: {total_in_scope}")
    print(f"  Net effect: FIX={overall.get('FIX',0)} - REGRESSION={overall.get('REGRESSION',0)} = {overall.get('FIX',0) - overall.get('REGRESSION',0)}")

    print("\n=== By n_fretted ===")
    for n in sorted(by_n):
        cats = by_n[n]
        in_scope = sum(v for k, v in cats.items() if not k.startswith("NA"))
        if in_scope == 0:
            continue
        fix = cats.get("FIX", 0)
        reg = cats.get("REGRESSION", 0)
        unc = cats.get("UNCHANGED", 0)
        diff = cats.get("DIFFERENT", 0)
        print(f"  n={n}: FIX={fix} ({100*fix/in_scope:.1f}%)  UNC={unc}  DIFF={diff}  REG={reg}  (in-scope={in_scope})")

    print("\n=== By error_type ===")
    for et, cats in sorted(by_type.items()):
        in_scope = sum(v for k, v in cats.items() if not k.startswith("NA"))
        if in_scope == 0:
            continue
        fix = cats.get("FIX", 0)
        reg = cats.get("REGRESSION", 0)
        print(f"  {et}: FIX={fix} ({100*fix/in_scope:.1f}%)  REG={reg}  (in-scope={in_scope})")

    print("\n=== Top chord roots by FIX count ===")
    top_fix = sorted(by_chord_root.items(), key=lambda x: -x[1].get("FIX", 0))[:10]
    for root, cats in top_fix:
        if cats.get("FIX", 0):
            print(f"  {root}: FIX={cats.get('FIX',0)}  UNC={cats.get('UNCHANGED',0)}  DIFF={cats.get('DIFFERENT',0)}  REG={cats.get('REGRESSION',0)}")

    print("\n=== Fix examples ===")
    for ex in fix_examples:
        print(f"  {ex['chord']:<10} frets={ex['frets']}  cur={ex['cur']}  alt={ex['alt']}  GT={ex['gt']}  FW={ex['fw']}  type={ex['type']}")

    print("\n=== Regression examples ===")
    for ex in regression_examples:
        print(f"  {ex['chord']:<10} frets={ex['frets']}  cur={ex['cur']}  alt={ex['alt']}  GT={ex['gt']}  FW={ex['fw']}  type={ex['type']}")


if __name__ == "__main__":
    main()
