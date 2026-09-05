"""Tests de la session d'écoute et de son transport WebSocket.

La session est testée seule (aucun serveur), puis via `/ws/listen` pour vérifier
que le protocole tient : démarrage, verdicts en cours de prise, bilan final, et
comportement face à une charge utile malformée.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from fretwise.listening.frames import Frame
from fretwise.listening.matching import CORRECT, MISSED, ExpectedNote
from fretwise.listening.pitch import midi_to_hz
from fretwise.listening.session import (
    ListeningSession,
    SessionError,
    parse_frames,
    parse_notes,
    score_to_dict,
    verdict_to_dict,
)
from fretwise.web.app import create_app

HOP = 0.008


def _frames_for(events: list[tuple[float, int]], total: float) -> list[Frame]:
    """Fabrique une série de trames « propres » : voisées sur les notes, muettes sinon.

    On court-circuite ici la détection de hauteur — elle a ses propres tests —
    pour n'éprouver que l'assemblage segmentation → appariement → score.
    """
    frames: list[Frame] = []
    t = 0.0
    while t < total:
        active = next(
            (m for onset, m in events if onset <= t < onset + 0.25), None
        )
        if active is None:
            frames.append(Frame(time=t, hz=0.0, confidence=0.0, rms=0.0, voiced=False))
        else:
            frames.append(
                Frame(
                    time=t,
                    hz=midi_to_hz(active),
                    confidence=0.97,
                    rms=0.2,
                    voiced=True,
                )
            )
        t += HOP
    return frames


def _expected(pairs: list[tuple[float, int]]) -> list[ExpectedNote]:
    return [
        ExpectedNote(onset=o, duration=0.25, midi=m, note_id=f"n{i}")
        for i, (o, m) in enumerate(pairs)
    ]


# ── Session ──────────────────────────────────────────────────────────────


def test_session_scores_a_faithful_take() -> None:
    phrase = [(0.5, 55), (1.0, 57), (1.5, 59)]
    session = ListeningSession.from_notes(_expected(phrase), hop_sec=HOP)
    live = session.feed(_frames_for(phrase, 2.2))
    remaining, score = session.finish()
    assert [v.status for v in live + remaining] == [CORRECT] * 3
    assert score.correct == 3
    assert score.score > 90.0


def test_session_reports_a_skipped_note() -> None:
    phrase = [(0.5, 55), (1.0, 57), (1.5, 59)]
    session = ListeningSession.from_notes(_expected(phrase), hop_sec=HOP)
    played = [(0.5, 55), (1.5, 59)]
    verdicts = session.feed(_frames_for(played, 2.2))
    remaining, score = session.finish()
    assert [v.status for v in verdicts + remaining] == [CORRECT, MISSED, CORRECT]
    assert score.missed == 1


def test_session_emits_verdicts_before_the_take_ends() -> None:
    # L'intérêt du direct : le premier verdict doit tomber pendant qu'on joue,
    # pas au coup de sifflet final.
    phrase = [(0.5, 55), (2.5, 57)]
    session = ListeningSession.from_notes(_expected(phrase), hop_sec=HOP)
    early = session.feed(_frames_for(phrase, 1.2))
    assert [v.status for v in early] == [CORRECT]


def test_session_on_an_empty_part_scores_zero() -> None:
    session = ListeningSession.from_notes([], hop_sec=HOP)
    session.feed(_frames_for([], 0.5))
    _remaining, score = session.finish()
    assert score.events == 0
    assert score.score == 0.0


# ── Décodage des charges utiles ──────────────────────────────────────────


def test_parse_notes_reads_a_well_formed_payload() -> None:
    notes = parse_notes([{"onset": 1.0, "duration": 0.5, "midi": 55, "id": "x"}])
    assert notes[0].note_id == "x"
    assert notes[0].midi == 55


def test_parse_notes_defaults_duration_but_never_pitch() -> None:
    assert parse_notes([{"onset": 1.0, "midi": 55}])[0].duration == 0.25
    for payload in ([{"onset": 1.0}], [{"midi": 55}], ["pas un objet"], "pas une liste"):
        try:
            parse_notes(payload)
        except SessionError:
            continue
        raise AssertionError(f"charge acceptée à tort : {payload!r}")


def test_parse_frames_accepts_compact_tuples() -> None:
    frames = parse_frames([[1.0, 440.0, 0.9, 0.2, True], [1.008, 0.0, 0.0, 0.0, False]])
    assert frames[0].hz == 440.0
    assert frames[1].voiced is False


def test_parse_frames_rejects_short_or_non_numeric_rows() -> None:
    for payload in ([[1.0, 440.0]], [[1.0, "la", 0.9, 0.2, True]], {"frames": []}):
        try:
            parse_frames(payload)
        except SessionError:
            continue
        raise AssertionError(f"charge acceptée à tort : {payload!r}")


def test_serialisation_converts_seconds_to_milliseconds() -> None:
    session = ListeningSession.from_notes(_expected([(0.5, 55)]), hop_sec=HOP)
    live = session.feed(_frames_for([(0.54, 55)], 1.2))
    remaining, score = session.finish()
    payload = verdict_to_dict((live + remaining)[0])
    assert payload["timing_error_ms"] is not None
    assert abs(payload["timing_error_ms"]) > 1.0      # ms, pas des secondes
    assert set(score_to_dict(score)) >= {"score", "correct", "missed", "timing_rms_ms"}


# ── Transport ────────────────────────────────────────────────────────────


def _ws_client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(tmp_path))


def test_websocket_full_take_returns_verdicts_then_score(tmp_path: Path) -> None:
    phrase = [(0.5, 55), (1.0, 57)]
    with _ws_client(tmp_path).websocket_connect("/ws/listen") as ws:
        ws.send_json({
            "type": "start",
            "hop_sec": HOP,
            "notes": [
                {"onset": o, "duration": 0.25, "midi": m, "id": f"n{i}"}
                for i, (o, m) in enumerate(phrase)
            ],
        })
        assert ws.receive_json() == {"type": "ready", "events": 2}

        statuses = []
        for frame in _frames_for(phrase, 1.6):
            ws.send_json({
                "type": "frames",
                "frames": [[frame.time, frame.hz, frame.confidence, frame.rms, frame.voiced]],
            })
        ws.send_json({"type": "stop"})
        message = ws.receive_json()
        while message["type"] == "verdicts":
            statuses += [v["status"] for v in message["verdicts"]]
            message = ws.receive_json()
        assert message["type"] == "score"
        statuses += [v["status"] for v in message["verdicts"]]
        assert statuses == [CORRECT, CORRECT]
        assert message["score"]["correct"] == 2
        ws.send_json({"type": "close"})


def test_websocket_rejects_frames_before_start(tmp_path: Path) -> None:
    with _ws_client(tmp_path).websocket_connect("/ws/listen") as ws:
        ws.send_json({"type": "frames", "frames": []})
        reply = ws.receive_json()
        assert reply["type"] == "error"
        ws.send_json({"type": "close"})


def test_websocket_reports_a_malformed_score_instead_of_dying(tmp_path: Path) -> None:
    # Une partition à moitié lue produirait un score faux sans que personne
    # ne s'en aperçoive : mieux vaut refuser la session.
    with _ws_client(tmp_path).websocket_connect("/ws/listen") as ws:
        ws.send_json({"type": "start", "notes": [{"onset": 1.0}]})
        reply = ws.receive_json()
        assert reply["type"] == "error"
        # la connexion reste utilisable après le refus
        ws.send_json({"type": "start", "notes": [{"onset": 1.0, "midi": 55}]})
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "close"})
