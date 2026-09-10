"""Hardware device drivers (multi-effects processors).

FretWise talks to two families of hardware, and the split from
:mod:`fretwise.gears` is deliberate:

* :mod:`fretwise.gears` is the **document** layer — per-song tone sheets, read on
  every ``/api/rig`` web request, deliberately stdlib-only.
* :mod:`fretwise.devices` is the **hardware** layer — network I/O against a real
  instrument on the LAN.

Keeping them apart means rendering a gear sheet never pulls in an HTTP stack.

The Valeton GP-180 predates this package and still lives in
:mod:`fretwise.rig_bank` (profiles, bindings, MIDI Program Change activation);
``devices/base.py`` is deliberately absent until a second implementation makes
the shared shape obvious rather than guessed.
"""

from __future__ import annotations

__all__ = ["headrush_core"]
