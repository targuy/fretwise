# data/gears — new-format GP-180 rig sheets

A **single flat directory** of per-song tone sheets in the **SongsGears** schema
(`skills/song-output-schema.json`). When a sheet exists here for a song, FretWise
shows it **in preference to** the legacy `.md` sheet — dropping a JSON in
supersedes the old curated data for that song.

```
data/gears/
├── ac-dc__highway-to-hell.json
├── arctic-monkeys__when-the-sun-goes-down.json
└── …
```

## Filename convention

Each file is named by the canonical key `<artist-slug>__<title-slug>.json` — see
[`fretwise.gears.naming.gears_key`](../../src/fretwise/gears/naming.py). `slugify`
is accent-stripped, lowercased, `&`→`and`, `/`→`-`, every other non-alphanumeric
run → `-`. Example: `ac-dc__highway-to-hell.json`. The same scheme lives in
SongsGears (`songs_gears.naming`) so generated files land at the right name.

The dir can be relocated outside the repo via the `gears_dir` setting.

## Superseding legacy data

As new-format sheets arrive, the matching legacy data (the song's entry in
`data/curated_facts*.json` and its generated `partitions/rigs/*.md`) is removed so
the JSON is the single source of truth:

```powershell
pixi run python tools/supersede_with_gears.py            # clean superseded legacy
pixi run python tools/supersede_with_gears.py --dry-run  # report only
```
