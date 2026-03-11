# Test Fixtures

Place GuitarPro files here to enable integration tests against real data.

## Accepted formats

- `.gp5` (recommended)
- `.gp4`
- `.gp3`

> **Note:** GP6/GP7 (`.gpx`) are not supported by PyGuitarPro.
> Convert via MuseScore: File → Export → Guitar Pro 5.

## Suggested fixtures for Sprint 1

Simple monophonic pieces work best for initial validation:

| File | Description |
|---|---|
| `ode_to_joy.gp5` | Beethoven — single-voice melody, no bends |
| `smoke_on_water.gp5` | Deep Purple — iconic riff, simple positions |
| `twinkle.gp5` | Children's song — slow tempo, open strings |
| `chromatic_scale.gp5` | All 12 notes across a single string |
| `pentatonic_pattern.gp5` | Position 1 pentatonic, typical beginner exercise |

## Usage

Integration tests in `tests/test_integration.py` automatically discover
any `.gp5`/`.gp4` file in this directory and run the full pipeline on it.

```
pytest tests/test_integration.py -v
```

## Privacy

Files in `tests/fixtures/private/` are excluded from version control
(see `.gitignore`).  Place licensed or personal GP files there.
