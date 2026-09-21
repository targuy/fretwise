"""Browser audio startup guards."""

from pathlib import Path


_MAIN_JS = Path(__file__).parents[1] / "src" / "fretwise" / "web" / "static" / "js" / "main.js"


def test_song_opening_defers_soundfont_loading_until_playback_intent() -> None:
    """Opening or clicking around a score must not start the synth download."""
    source = _MAIN_JS.read_text(encoding="utf-8")
    initial = source[source.index("// Audio starts on the first explicit user gesture"):
                     source.index("// The engine owns one gesture-unlock listener")]
    unlock = source[source.index("function _unlockAudioOnFirstGesture()"):
                    source.index("['pointerdown', 'keydown', 'touchstart']", source.index("function _unlockAudioOnFirstGesture()"))]

    assert "playback.enableAudio()" not in initial
    assert "playback.enableAudio()" not in unlock
    assert "async function _startPlaybackAfterInstrumentReady()" in source
    assert "await engine.prepareAudioForPlayback();" in source
    play_handler = source[source.index("if (btnPlay) {"):
                          source.index("if (btnPrev)", source.index("if (btnPlay) {"))]
    assert "void _startPlaybackAfterInstrumentReady();" in play_handler
    assert "playback.enableAudio();" in play_handler
    assert "playback.toggle();" not in play_handler
