# Valeton GP-180 MIDI and Rig-Bank Notes

This note records the implementation assumptions used by FretWise for GP-180 rig
profile activation.

## Sources checked

- `docs/1775627728688.GP-180_Online Manual_EN_Firmware V1.0.0.pdf`
- Notion page: `Valeton GP-180`
- Notion page: `Référentiels GP-180`
- Local Valeton Suite install:
  `C:\Program Files\Valeton Suite\Valeton Suite`

## MIDI preset selection

The GP-180 manual's MIDI Control Information List maps patch selection as:

| GP-180 patch | MIDI messages |
|---|---|
| 001-128 | `CC0 = 0`, then `PC = 0-127` |
| 129-200 | `CC0 = 1`, then `PC = 0-71` |

FretWise stores `RigProfile.program` as a zero-based value (`0..199`):

- `program=0` selects GP-180 patch `001` with `PC 0`
- `program=127` selects patch `128` with `PC 127`
- `program=128` selects patch `129` with `CC0 1`, `PC 0`
- `program=199` selects patch `200` with `CC0 1`, `PC 71`

MIDI input can come from TRS, USB, Bluetooth, or Mixed mode. For USB control from
FretWise, set the GP-180 global MIDI input source to `USB Only` or `Mixed`, and
set the USB input channel to either `Omni` or the channel configured on the
FretWise rig profile.

## Control Change commands found in the manual

The manual lists these useful CC commands:

- `CC7`: patch volume (`0-100`)
- `CC11`: expression parameter (`0-100`)
- `CC13`: expression A/B state switching
- `CC16`, `CC18`, `CC20`: quick access parameters (`0-100`)
- `CC17`, `CC19`, `CC21`: quick access step down/up
- `CC24`: patch down
- `CC25`: patch up
- `CC28`: unit mode, patch mode (`0-63`) or stomp mode (`64-127`)
- `CC48-59`: module on/off in GP-180 chain order
- `CC60`: tuner
- `CC61-68`: looper controls and levels
- `CC69-71`: CTRL A/B/C
- `CC73-74`: tempo value
- `CC75`: tap tempo
- `CC92-96`: drum machine controls
- `CC115`: analog bypass
- `CC116`: DSP bypass

## Valeton Suite local data

The installed Valeton Suite application is a Flutter app. Its bundled
`module*_data.json` files contain effect model catalogs and parameter metadata.
They are useful for validating effect names, but they do not appear to contain
user preset names or live bank assignments.

Observed useful files:

- `data\flutter_assets\assets\data\module_data.json`
- `data\flutter_assets\assets\data\module150_data.json`
- `data\flutter_assets\assets\data\module50_data.json`
- `data\flutter_assets\assets\data\gp5D.json`

`gp5D.json` describes drum/metronome patterns, not GP-180 rig presets.

## FretWise model

The structured bank is `rig_bank.json` in the existing `rigs` directory. It is
separate from the FretWise player `profile` module because GP-180 rigs are
performance metadata and device control, not biomechanical scoring input.

Resolution order:

1. explicit profile id
2. song binding
3. artist binding
4. genre binding
5. profile artist metadata
6. profile genre metadata
