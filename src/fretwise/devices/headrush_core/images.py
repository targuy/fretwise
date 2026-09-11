"""Pictures of the Core's blocks, exactly as its own Remote Editor shows them.

The Core serves one WebP per block model under :data:`IMAGE_ROOT`. The path rule
comes from the Remote Editor's bundle (``static/js/main.*.js``, function ``OA``):

* amps (``Amp``, ``ReValver Amp``): ``Amp/<amp model label>.webp``;
* cabs (``Cab``, ``ReValver Cab``): ``Cab/<cab type label>.webp``;
* anything else: ``<block name>.webp`` — a second instance ("Amp 2") uses the
  picture of the first.

They are HeadRush's artwork, stored on the user's own instrument, so FretWise
never ships them: they are fetched from the device on first use and cached next
to the rig store, outside git and the Docker image.
"""

from __future__ import annotations

import hashlib
import re
import time
import urllib.parse
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from fretwise.devices.headrush_core.catalog import Catalog
from fretwise.devices.headrush_core.client import DeviceError, DeviceNotFoundError

#: Where the device serves block pictures.
IMAGE_ROOT = "/files/Evil/Web/Blocks/img"

_AMPS = frozenset({"Amp", "ReValver Amp"})
_CABS = frozenset({"Cab", "ReValver Cab"})

#: RIFF container + WEBP form type: anything else is not served as an image.
_WEBP_MAGIC = (b"RIFF", b"WEBP")


def base_module(module: str) -> str:
    """Return the first-instance name of a block ("Amp 2" -> "Amp")."""
    return module[:-2] if module.endswith(" 2") else module


def image_variant(module: str, params: Mapping[str, Any]) -> str:
    """Return the model label that selects an amp's or cab's picture, else ``""``."""
    base = base_module(module)
    if base in _AMPS:
        return str(params.get("Type") or "")
    if base in _CABS:
        return str(params.get("CabType") or "")
    return ""


def image_relpath(catalog: Catalog, module: str, variant: str = "") -> str:
    """Return a block picture's path under :data:`IMAGE_ROOT`, without extension.

    Every component is checked against the catalog, so nothing but a real block
    or model name can reach the URL built from it.

    Raises:
        ValueError: Unknown block, or a variant that is not one of its models.
    """
    base = base_module(module)
    block = catalog.block(base) or catalog.block(module)
    if block is None:
        raise ValueError(f"bloc inconnu du catalogue : {module!r}")
    if variant and (base in _AMPS or base in _CABS):
        key, folder = ("Type", "Amp") if base in _AMPS else ("CabType", "Cab")
        param = block.param(key)
        if param is None or variant not in param.options:
            raise ValueError(f"{variant!r} n'est pas un modèle de {base!r}")
        return f"{folder}/{variant}"
    return base


def all_image_relpaths(catalog: Catalog) -> list[str]:
    """Return every picture the device can serve: each block, each amp, each cab."""
    found: dict[str, None] = {}
    for name in catalog.module_types:
        base = base_module(name)
        if base and base != "Empty Slot" and catalog.block(base) is not None:
            found[base] = None
    for names, key, folder in ((_AMPS, "Type", "Amp"), (_CABS, "CabType", "Cab")):
        for name in sorted(names):
            block = catalog.block(name)
            param = block.param(key) if block else None
            for option in param.options if param else ():
                found[f"{folder}/{option}"] = None
    return list(found)


def image_url_path(relpath: str) -> str:
    """Return the device URL path of a picture, each segment percent-encoded."""
    segments = "/".join(urllib.parse.quote(part, safe="") for part in relpath.split("/"))
    return f"{IMAGE_ROOT}/{segments}.webp"


def cache_name(relpath: str) -> str:
    """Return a safe, unique file name for a picture in the cache."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", relpath).strip("._") or "block"
    digest = hashlib.sha1(relpath.encode("utf-8")).hexdigest()[:8]
    return f"{slug[:80]}-{digest}.webp"


def is_webp(data: bytes) -> bool:
    """Return True when ``data`` starts like a WebP file."""
    return len(data) > 12 and data[:4] == _WEBP_MAGIC[0] and data[8:12] == _WEBP_MAGIC[1]


class ImageCache:
    """On-disk cache of block pictures, with a short memory of failures.

    A rig view asks for half a dozen pictures at once; with the Core switched off
    each would otherwise wait for its own connection timeout. After one failure
    to reach the device, requests fail immediately for ``retry_after_s``; a
    picture the device answered 404 for is not asked again in this process.
    """

    def __init__(
        self,
        directory: Path,
        *,
        retry_after_s: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.directory = directory
        self.retry_after_s = retry_after_s
        self._clock = clock
        self._missing: set[str] = set()
        self._offline_until = 0.0

    @property
    def offline(self) -> bool:
        """Return True while the device is considered unreachable."""
        return self._clock() < self._offline_until

    def path(self, relpath: str) -> Path:
        """Return where a picture is (or would be) cached."""
        return self.directory / cache_name(relpath)

    def get(self, relpath: str) -> Path | None:
        """Return the cached picture, or None."""
        path = self.path(relpath)
        return path if path.is_file() else None

    def fetch(self, relpath: str, fetcher: Callable[[str], bytes]) -> Path | None:
        """Return the cached picture, downloading it with ``fetcher`` when absent.

        Args:
            relpath: Picture path from :func:`image_relpath`.
            fetcher: Callable taking the device URL path and returning its bytes.

        Returns:
            The cached file, or None when the device lacks it or is unreachable.
        """
        cached = self.get(relpath)
        if cached is not None:
            return cached
        if relpath in self._missing or self.offline:
            return None
        try:
            data = fetcher(image_url_path(relpath))
        except DeviceNotFoundError:
            self._missing.add(relpath)
            return None
        except DeviceError:
            self._offline_until = self._clock() + self.retry_after_s
            return None
        if not is_webp(data):
            self._missing.add(relpath)
            return None
        path = self.path(relpath)
        self.directory.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(".part")
        partial.write_bytes(data)
        partial.replace(path)
        return path


__all__ = [
    "IMAGE_ROOT",
    "ImageCache",
    "all_image_relpaths",
    "base_module",
    "cache_name",
    "image_relpath",
    "image_url_path",
    "image_variant",
    "is_webp",
]
