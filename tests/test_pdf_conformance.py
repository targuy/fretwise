"""Tests for shared PDF conformance report contract."""

from __future__ import annotations

import json

from fretwise.pdf_conformance import (
    core_pdf_conformance_report,
    legacy_shadow_pdf_conformance_report,
)


def test_core_pdf_conformance_report_serialization() -> None:
    report = core_pdf_conformance_report(3)
    payload = report.to_dict()
    header_payload = json.loads(report.to_header_value())

    assert payload["engine"] == "core"
    assert payload["scope"] == "engine"
    assert payload["issue_count"] == 3
    assert payload["shadow_engine"] is None
    assert payload["shadow_failed"] is False
    assert header_payload == payload


def test_legacy_shadow_pdf_conformance_report_serialization() -> None:
    report = legacy_shadow_pdf_conformance_report(2, shadow_failed=True)
    payload = report.to_dict()
    header_payload = json.loads(report.to_header_value())

    assert payload["engine"] == "legacy"
    assert payload["scope"] == "shadow"
    assert payload["issue_count"] == 2
    assert payload["shadow_engine"] == "core"
    assert payload["shadow_failed"] is True
    assert header_payload == payload

