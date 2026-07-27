"""Diagnose why the GP-180 does not react to FretWise MIDI activation.

FretWise's send path can only prove that bytes left the computer. When the pedal
does not move, the question is always the same: does it receive them, and does it
act on them? These probes separate those two failures.

Usage (from the repo root)::

    pixi run python tools/gp180_midi_diag.py ports
    pixi run python tools/gp180_midi_diag.py listen [seconds]
    pixi run python tools/gp180_midi_diag.py echo
    pixi run python tools/gp180_midi_diag.py sweep [program]
    pixi run python tools/gp180_midi_diag.py pc <program> [channel]

``ports``   list MIDI ports and flag the GP-180. Its name carries a trailing
            rtmidi index that shifts when other MIDI gear is plugged in.
``listen``  dump what the pedal transmits. Change presets by hand: the channel it
            TRANSMITS on is normally the one it also LISTENS on.
``echo``    send a Program Change and watch whether it comes back on the pedal's
            MIDI OUT. A returning echo proves USB MIDI IN reaches the device, so
            a pedal that still does not switch is refusing to *act*, not failing
            to receive — look at its MIDI channel and at patch/stomp mode.
``sweep``   send the same Program Change on all 16 channels, pausing between each
            so you can watch the display and see which channel it answers on.
``pc``      send one Program Change on one channel.
"""
from __future__ import annotations

import sys
import time

import mido

from fretwise.rig_bank import find_device_output_name

DEVICE = "valeton_gp180"


def _out_name() -> str:
    name = find_device_output_name(DEVICE, mido.get_output_names())
    if not name:
        raise SystemExit(
            "GP-180 MIDI output not found. Connect it over USB and enable "
            f"Global > MIDI > USB. Ports: {mido.get_output_names()}"
        )
    return name


def _in_name() -> str | None:
    return find_device_output_name(DEVICE, mido.get_input_names())


def ports() -> None:
    for label, names in (("OUTPUTS", mido.get_output_names()), ("INPUTS", mido.get_input_names())):
        print(f"=== {label} ===")
        for index, name in enumerate(names):
            mark = "  <-- GP-180" if find_device_output_name(DEVICE, [name]) else ""
            print(f"  [{index}] {name!r}{mark}")


def listen(seconds: int = 25) -> None:
    name = _in_name()
    if not name:
        raise SystemExit("No GP-180 MIDI input port. Enable its USB MIDI output.")
    print(f"Listening on {name!r} for {seconds}s.")
    print("--> Change presets on the GP-180 by hand now.\n")
    seen: list[mido.Message] = []
    with mido.open_input(name) as port:
        deadline = time.time() + seconds
        while time.time() < deadline:
            for msg in port.iter_pending():
                if msg.type == "clock":  # the pedal streams clock constantly
                    continue
                seen.append(msg)
                channel = f" ch={msg.channel + 1}" if hasattr(msg, "channel") else ""
                print(f"  RX {msg.type}{channel}: {msg}")
            time.sleep(0.01)
    if not seen:
        print("\nNOTHING RECEIVED (clock ignored).")
        print("Check on the pedal: Global > MIDI > USB / Mixed, and MIDI Out/Thru.")
        return
    channels = sorted({m.channel + 1 for m in seen if hasattr(m, "channel")})
    print(f"\n{len(seen)} non-clock messages. Channels seen (1-based): {channels}")
    programs = [(m.channel + 1, m.program) for m in seen if m.type == "program_change"]
    if programs:
        print(f"Program changes (channel, program): {programs}")
        print(f"\n=> Set the rig-bank midi_channel to {programs[0][0]}.")


def echo(program: int = 5, channel: int = 1) -> None:
    out_name, in_name = _out_name(), _in_name()
    if not in_name:
        raise SystemExit("No GP-180 MIDI input port, cannot watch for an echo.")
    with mido.open_input(in_name) as inp, mido.open_output(out_name) as out:
        time.sleep(0.3)
        for _ in inp.iter_pending():
            pass  # drain
        out.send(mido.Message("control_change", channel=channel - 1, control=0, value=0))
        out.send(mido.Message("program_change", channel=channel - 1, program=program))
        time.sleep(1.5)
        replies = [m for m in inp.iter_pending() if m.type != "clock"]
    print(f"Sent PC {program} on channel {channel}; {len(replies)} non-clock replies:")
    for msg in replies[:8]:
        print(f"  {msg}")
    if any(m.type == "program_change" for m in replies):
        print("\n=> The pedal echoed the Program Change: USB MIDI IN reaches it.")
        print("   If it still does not switch, it is not ACTING on the message.")
        print("   Check its MIDI channel, and patch mode vs stomp mode (CC28).")
    else:
        print("\n=> No echo. Either MIDI Thru/Out is off, or USB MIDI IN is not active.")


def sweep(program: int = 5, delay: float = 1.5) -> None:
    name = _out_name()
    print(f"Sweeping Program Change {program} across channels 1..16 on {name!r}.")
    print("--> Watch the GP-180 display; note which channel makes it change.\n")
    with mido.open_output(name) as port:
        for channel in range(16):
            port.send(mido.Message("control_change", channel=channel, control=0, value=0))
            port.send(mido.Message("program_change", channel=channel, program=program))
            print(f"  channel {channel + 1:>2} sent (CC0=0, PC={program})")
            time.sleep(delay)
    print("\nDone. If the pedal never moved, it is not acting on USB Program Changes.")


def pc(program: int, channel: int = 1) -> None:
    with mido.open_output(_out_name()) as port:
        port.send(mido.Message("control_change", channel=channel - 1, control=0, value=0))
        port.send(mido.Message("program_change", channel=channel - 1, program=program))
    print(f"Sent PC {program} on channel {channel} (GP-180 patch {program + 1:03d}).")


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "ports"
    argument = int(sys.argv[2]) if len(sys.argv) > 2 else None
    if command == "ports":
        ports()
    elif command == "listen":
        listen(argument if argument is not None else 25)
    elif command == "echo":
        echo(argument if argument is not None else 5)
    elif command == "sweep":
        sweep(argument if argument is not None else 5)
    elif command == "pc":
        if argument is None:
            raise SystemExit("pc needs a program number: pc <program> [channel]")
        pc(argument, int(sys.argv[3]) if len(sys.argv) > 3 else 1)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
