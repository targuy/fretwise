"""Shared pytest fixtures and helpers for FretWise tests.

Provides:
- ``render_svg_to_image``  — SVG string → PIL Image via PyMuPDF (no native cairo needed)
- ``assert_visual_match`` — compares an image against a stored snapshot (PNG)
- ``--update-snapshots``  — CLI flag to regenerate all snapshots
- ``@pytest.mark.visual`` — marker to run (or skip) snapshot tests
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pytest
from PIL import Image

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Directory where PNG snapshots are stored
# ---------------------------------------------------------------------------
SNAPSHOTS_DIR = Path(__file__).parent / "snapshots"

# ---------------------------------------------------------------------------
# Pytest CLI options
# ---------------------------------------------------------------------------


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--update-snapshots",
        action="store_true",
        default=False,
        help="Regenerate all visual snapshot PNGs instead of comparing them.",
    )


# ---------------------------------------------------------------------------
# PyMuPDF-based SVG → PIL Image renderer
# ---------------------------------------------------------------------------


def render_svg_to_image(svg: str, *, dpi: int = 96) -> Image.Image:
    """Render an SVG string to a PIL RGBA image using PyMuPDF (no native cairo).

    Args:
        svg: Complete SVG document string.
        dpi: Rendering resolution (default 96 DPI ≈ 100 % zoom).

    Returns:
        A PIL Image in RGBA mode.
    """
    import fitz  # PyMuPDF — included as optional dep for dev

    doc = fitz.open(stream=svg.encode("utf-8"), filetype="svg")
    page = doc[0]
    pix = page.get_pixmap(dpi=dpi)
    png_bytes = pix.tobytes("png")
    return Image.open(io.BytesIO(png_bytes)).convert("RGBA")


# ---------------------------------------------------------------------------
# Visual comparison helper
# ---------------------------------------------------------------------------


def assert_visual_match(
    img: Image.Image,
    snapshot_name: str,
    *,
    threshold: float = 0.97,
    update: bool = False,
) -> None:
    """Assert *img* visually matches the stored snapshot PNG.

    If no snapshot exists yet (or ``update=True``), the image is saved and the
    test passes automatically.

    Similarity is measured as 1 − normalised_MSE, so perfect match = 1.0.
    The default *threshold* of 0.97 allows for minor anti-aliasing drift.

    Args:
        img: The image rendered in this test run.
        snapshot_name: Filename stem (without .png) stored under tests/snapshots/.
        threshold: Minimum acceptable similarity (0–1).  Default: 0.97.
        update: If True, always overwrite the snapshot (set via conftest flag).
    """
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_path = SNAPSHOTS_DIR / f"{snapshot_name}.png"

    if update or not snapshot_path.exists():
        img.save(snapshot_path)
        return  # snapshot created — test passes

    reference = Image.open(snapshot_path).convert("RGBA")

    # Resize current image to match reference if sizes differ (layout drift guard)
    if img.size != reference.size:
        pytest.fail(
            f"Image size mismatch for '{snapshot_name}': "
            f"got {img.size}, expected {reference.size}. "
            "Run with --update-snapshots to regenerate."
        )

    arr_img = np.asarray(img, dtype=np.float32)
    arr_ref = np.asarray(reference, dtype=np.float32)
    mse = float(np.mean((arr_img - arr_ref) ** 2))
    similarity = 1.0 - mse / (255.0 ** 2)

    if similarity < threshold:
        # Save a diff image next to the snapshot for inspection
        diff_path = SNAPSHOTS_DIR / f"{snapshot_name}_diff.png"
        diff_arr = np.abs(arr_img - arr_ref).clip(0, 255).astype(np.uint8)
        Image.fromarray(diff_arr[:, :, :3]).save(diff_path)

        pytest.fail(
            f"Visual regression for '{snapshot_name}': "
            f"similarity={similarity:.4f} < threshold={threshold}. "
            f"Diff saved to {diff_path}. "
            "Run with --update-snapshots to regenerate."
        )


# ---------------------------------------------------------------------------
# Pytest fixture: --update-snapshots flag forwarded to tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def update_snapshots(request: pytest.FixtureRequest) -> bool:
    """Return True when the test run was started with --update-snapshots."""
    return bool(request.config.getoption("--update-snapshots"))


# ---------------------------------------------------------------------------
# Pytest marker registration
# ---------------------------------------------------------------------------


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "visual: mark a test as a visual snapshot regression test (may be slow).",
    )
