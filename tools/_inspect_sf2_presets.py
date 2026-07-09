"""One-off: list SF2/SF3 preset headers (name, GM program, bank) for a soundfont.

Usage: pixi run python tools/_inspect_sf2_presets.py data/sounds/alex_gm.sf3
"""
import struct
import sys
from pathlib import Path


def find_chunk(data: bytes, fourcc: bytes, start: int, end: int) -> tuple[int, int] | None:
    pos = start
    while pos < end - 8:
        cid = data[pos:pos + 4]
        size = struct.unpack_from("<I", data, pos + 4)[0]
        if cid == fourcc:
            return pos + 8, pos + 8 + size
        pos += 8 + size + (size & 1)
    return None


def main(path: str) -> None:
    data = Path(path).read_bytes()
    assert data[0:4] == b"RIFF" and data[8:12] == b"sfbk", "not an SF2/SF3 RIFF"
    riff_end = 8 + struct.unpack_from("<I", data, 4)[0]
    # Top-level LIST chunks: INFO, sdta, pdta
    pos = 12
    pdta = None
    while pos < riff_end - 8:
        cid = data[pos:pos + 4]
        size = struct.unpack_from("<I", data, pos + 4)[0]
        body_start = pos + 8
        if cid == b"LIST" and data[body_start:body_start + 4] == b"pdta":
            pdta = (body_start + 4, body_start + size)
        pos = body_start + size + (size & 1)
    assert pdta, "no pdta chunk found"
    phdr = find_chunk(data, b"phdr", pdta[0], pdta[1])
    assert phdr, "no phdr subchunk found"
    start, end = phdr
    n = (end - start) // 38
    presets = []
    for i in range(n):
        rec = data[start + i * 38: start + (i + 1) * 38]
        name = rec[0:20].split(b"\x00", 1)[0].decode("latin-1")
        preset_num, bank = struct.unpack_from("<HH", rec, 20)
        presets.append((name, preset_num, bank))
    presets.sort(key=lambda p: (p[2], p[1]))
    for name, preset_num, bank in presets:
        if preset_num == 0 or name.upper() == "EOP":
            continue
    for name, preset_num, bank in presets:
        print(f"bank={bank:3d} program={preset_num:3d}  {name}")


if __name__ == "__main__":
    main(sys.argv[1])
