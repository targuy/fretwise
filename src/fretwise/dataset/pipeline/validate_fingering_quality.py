"""Cross-validate fingering quality across all data sources.

Checks for:
1. Physical impossibility (same finger on different non-adjacent frets)
2. Finger ordering violations (lower fret should have lower finger)
3. Extreme stretches (> 5 frets between index and pinky)
4. Cross-source disagreements (same chord name, different fingering)
5. Missing finger assignments on fretted notes
"""

import json
from collections import Counter, defaultdict

from fretwise.dataset.config import PROCESSED_DIR

FINGER_NAMES = {1: "INDEX", 2: "MIDDLE", 3: "RING", 4: "PINKY"}


def load_dataset():
    with open(PROCESSED_DIR / "chord_dataset.json", encoding="utf-8") as f:
        return json.load(f)


def check_physical_validity(chord: dict) -> list[str]:
    """Check if a fingering is physically possible."""
    issues = []
    strings = chord["strings"]
    fingers = chord["fingers"]

    fretted = []
    for i in range(6):
        if strings[i] is not None and strings[i] > 0 and fingers[i] is not None and fingers[i] > 0:
            fretted.append((i, strings[i], fingers[i]))

    if len(fretted) < 2:
        return issues

    # Check 1: Same finger on non-adjacent frets (except INDEX barre)
    finger_frets = defaultdict(set)
    for _, fret, finger in fretted:
        finger_frets[finger].add(fret)

    for finger, frets in finger_frets.items():
        if len(frets) > 1:
            sorted_frets = sorted(frets)
            span = sorted_frets[-1] - sorted_frets[0]
            # INDEX can span 1 fret (partial barre), others cannot
            if finger == 1 and span <= 1:
                continue
            if span > 0:
                issues.append(f"duplicate_finger:{FINGER_NAMES.get(finger, '?')}:span={span}")

    # Check 2: Finger ordering
    sorted_by_fret = sorted(fretted, key=lambda x: (x[1], x[0]))
    for i in range(len(sorted_by_fret) - 1):
        _, fret_a, finger_a = sorted_by_fret[i]
        _, fret_b, finger_b = sorted_by_fret[i + 1]
        if fret_a < fret_b and finger_a > finger_b:
            issues.append(f"ordering:{FINGER_NAMES.get(finger_a, '?')}@{fret_a}>{FINGER_NAMES.get(finger_b, '?')}@{fret_b}")

    # Check 3: Extreme stretch
    if 1 in finger_frets and 4 in finger_frets:
        index_max = max(finger_frets[1])
        pinky_min = min(finger_frets[4])
        if pinky_min > index_max and pinky_min - index_max > 5:
            issues.append(f"extreme_stretch:{pinky_min - index_max}_frets")

    return issues


def check_missing_fingers(chord: dict) -> int:
    """Count fretted notes without finger assignment."""
    strings = chord["strings"]
    fingers = chord["fingers"]
    missing = 0
    for i in range(6):
        if strings[i] is not None and strings[i] > 0:
            if fingers[i] is None or fingers[i] == 0:
                missing += 1
    return missing


def find_cross_source_disagreements(chords: list[dict]) -> list[dict]:
    """Find same-name chords with different fingerings across sources."""
    by_shape = defaultdict(list)
    for chord in chords:
        key = (chord["name"], tuple(chord["strings"]))
        by_shape[key].append(chord)

    disagreements = []
    for key, group in by_shape.items():
        if len(group) < 2:
            continue
        sources = set(c.get("source", "?") for c in group)
        if len(sources) < 2:
            continue

        # Check if fingerings differ
        fingerings = set(tuple(c["fingers"]) for c in group)
        if len(fingerings) > 1:
            disagreements.append({
                "name": key[0],
                "strings": list(key[1]),
                "fingerings": [
                    {"fingers": c["fingers"], "source": c.get("source", "?")}
                    for c in group
                ],
            })

    return disagreements


def main():
    chords = load_dataset()
    print(f"Dataset: {len(chords)} chords")
    print()

    # By source
    sources = Counter(c.get("source", "unknown") for c in chords)
    print("Sources:")
    for src, count in sources.most_common():
        print(f"  {src}: {count}")
    print()

    # Physical validity
    print("=" * 60)
    print("PHYSICAL VALIDITY CHECK")
    print("=" * 60)

    issues_by_type = defaultdict(int)
    issues_by_source = defaultdict(int)
    chords_with_issues = 0

    for chord in chords:
        issues = check_physical_validity(chord)
        if issues:
            chords_with_issues += 1
            source = chord.get("source", "unknown")
            issues_by_source[source] += 1
            for issue in issues:
                issue_type = issue.split(":")[0]
                issues_by_type[issue_type] += 1

    print(f"\n  Chords with physical issues: {chords_with_issues}/{len(chords)} "
          f"({chords_with_issues/len(chords)*100:.1f}%)")
    print("\n  By issue type:")
    for issue_type, count in sorted(issues_by_type.items(), key=lambda x: -x[1]):
        print(f"    {issue_type}: {count}")
    print("\n  By source:")
    for source, count in sorted(issues_by_source.items(), key=lambda x: -x[1]):
        total = sources[source]
        print(f"    {source}: {count}/{total} ({count/total*100:.1f}%)")

    # Missing fingers
    print(f"\n{'='*60}")
    print("MISSING FINGER ASSIGNMENTS")
    print("=" * 60)

    missing_by_source = defaultdict(int)
    total_missing = 0
    for chord in chords:
        m = check_missing_fingers(chord)
        if m > 0:
            total_missing += m
            missing_by_source[chord.get("source", "unknown")] += m

    print(f"\n  Total missing assignments: {total_missing}")
    for source, count in sorted(missing_by_source.items(), key=lambda x: -x[1]):
        print(f"    {source}: {count}")

    # Cross-source disagreements
    print(f"\n{'='*60}")
    print("CROSS-SOURCE DISAGREEMENTS")
    print("=" * 60)

    disagreements = find_cross_source_disagreements(chords)
    print(f"\n  Total disagreements: {len(disagreements)}")
    if disagreements:
        print("\n  Examples (first 5):")
        for d in disagreements[:5]:
            print(f"    {d['name']} {d['strings']}:")
            for f in d["fingerings"]:
                print(f"      {f['source']}: {f['fingers']}")

    # Quality score per source
    print(f"\n{'='*60}")
    print("SOURCE QUALITY SUMMARY")
    print("=" * 60)

    for source in sorted(sources.keys()):
        total = sources[source]
        issues = issues_by_source.get(source, 0)
        missing = missing_by_source.get(source, 0)
        quality_pct = (1 - issues / total) * 100
        print(f"\n  {source} ({total} chords):")
        print(f"    Physical validity: {quality_pct:.1f}%")
        print(f"    Missing fingers:   {missing}")


if __name__ == "__main__":
    main()
