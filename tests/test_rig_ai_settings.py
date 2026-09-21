"""Private credential storage and public-only AI settings contracts."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from fretwise.rig_ai import RigAIError, get_settings, save_settings, settings

FAKE_KEY = "unit-test-credential-not-a-real-api-key"


@pytest.fixture(autouse=True)
def isolated_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FRETWISE_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("FRETWISE_RIG_AI_SECRETS_FILE", str(tmp_path / "rig-ai-secrets.json"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_defaults_have_no_credentials_and_never_create_files(tmp_path: Path) -> None:
    public = get_settings()
    assert public["mode"] == "manual"
    assert public["openai"]["model"] == "gpt-5.6-terra"
    assert public["webSearch"] is True
    assert public["openai"]["configured"] is False
    assert public["anthropic"]["keySource"] == "none"
    assert list(tmp_path.iterdir()) == []


def test_key_is_private_and_preferences_do_not_overwrite_web_or_cloud(tmp_path: Path) -> None:
    unrelated = {"cloud": "preserved"}
    (tmp_path / "config.json").write_text(json.dumps(unrelated))
    (tmp_path / "secrets.json").write_text(json.dumps(unrelated))
    public = save_settings(
        {
            "mode": "openai",
            "openai_api_key": FAKE_KEY,
            "openai_model": "gpt-5-mini",
            "web_search": False,
        }
    )
    assert FAKE_KEY not in json.dumps(public)
    assert public["openai"] == {
        "configured": True,
        "keySource": "file",
        "editable": True,
        "model": "gpt-5-mini",
    }
    assert json.loads((tmp_path / "rig-ai-secrets.json").read_text())["OPENAI_API_KEY"] == FAKE_KEY
    assert FAKE_KEY not in (tmp_path / "rig-ai.json").read_text()
    assert json.loads((tmp_path / "config.json").read_text()) == unrelated
    assert json.loads((tmp_path / "secrets.json").read_text()) == unrelated
    assert not list(tmp_path.glob(".*.json.*"))
    if os.name != "nt":
        assert (tmp_path / "rig-ai-secrets.json").stat().st_mode & 0o777 == 0o600


def test_blank_preserves_key_and_clear_removes_only_requested_key(tmp_path: Path) -> None:
    save_settings({"openai_api_key": FAKE_KEY, "anthropic_api_key": FAKE_KEY + "-anthropic"})
    assert save_settings({"openai_api_key": ""})["openai"]["configured"] is True
    public = save_settings({"clear_openai_key": True})
    assert public["openai"]["configured"] is False
    assert public["anthropic"]["configured"] is True
    secrets = json.loads((tmp_path / "rig-ai-secrets.json").read_text())
    assert "OPENAI_API_KEY" not in secrets
    assert "ANTHROPIC_API_KEY" in secrets


@pytest.mark.parametrize(
    "update",
    [
        {"openai_api_key": FAKE_KEY},
        {"clear_openai_key": True},
    ],
)
def test_environment_key_is_locked(
    update: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY + "-env")
    public = get_settings()
    assert public["openai"]["configured"] is True
    assert public["openai"]["keySource"] == "environment"
    assert public["openai"]["editable"] is False
    assert FAKE_KEY not in json.dumps(public)
    with pytest.raises(RigAIError) as error:
        save_settings(update)
    assert error.value.code == "key_locked"


@pytest.mark.parametrize(
    "updates",
    [
        {"mode": "other"},
        {"web_search": "true"},
        {"openai_model": "bad\nmodel"},
        {"openai_api_key": "short"},
        {"openai_api_key": FAKE_KEY + "\nHeader: injected"},
        {"openai_api_key": FAKE_KEY, "clear_openai_key": True},
        {"clear_openai_key": "true"},
        {"openai_api_key": None},
        {"unknown": FAKE_KEY},
    ],
)
def test_invalid_updates_do_not_write_and_do_not_echo_values(
    updates: dict[str, object],
    tmp_path: Path,
) -> None:
    with pytest.raises(RigAIError) as error:
        save_settings(updates)
    assert FAKE_KEY not in str(error.value)
    assert list(tmp_path.iterdir()) == []


def test_invalid_secret_store_is_not_overwritten(tmp_path: Path) -> None:
    secret_file = tmp_path / "rig-ai-secrets.json"
    secret_file.write_text("broken-store-with-" + FAKE_KEY)
    with pytest.raises(RigAIError) as error:
        save_settings({"openai_api_key": FAKE_KEY})
    assert error.value.code == "storage_unavailable"
    assert FAKE_KEY not in str(error.value)
    assert secret_file.read_text() == "broken-store-with-" + FAKE_KEY


def test_storage_failure_preserves_old_file_and_removes_temporary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_settings({"openai_api_key": FAKE_KEY})
    previous = (tmp_path / "rig-ai-secrets.json").read_bytes()

    def fail_replace(*args: object) -> None:
        raise OSError("irrelevant error containing " + FAKE_KEY)

    monkeypatch.setattr(settings.os, "replace", fail_replace)
    with pytest.raises(RigAIError) as error:
        save_settings({"clear_openai_key": True})
    assert FAKE_KEY not in str(error.value)
    assert (tmp_path / "rig-ai-secrets.json").read_bytes() == previous
    assert not list(tmp_path.glob(".*.json.*"))


def test_symlink_destination_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    destination = tmp_path / "rig-ai-secrets.json"
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == destination or original(path))
    with pytest.raises(RigAIError) as error:
        save_settings({"openai_api_key": FAKE_KEY})
    assert error.value.code == "storage_unsafe"
    assert not destination.exists()


def test_permissions_applied_before_any_key_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protected: list[Path] = []
    original = settings._private_file

    def check_private(path: Path) -> None:
        assert path.read_bytes() == b""
        original(path)
        protected.append(path)

    monkeypatch.setattr(settings, "_private_file", check_private)
    save_settings({"openai_api_key": FAKE_KEY})
    assert len(protected) == 1


def test_manual_or_unconfigured_mode_never_provides_credentials() -> None:
    with pytest.raises(RigAIError, match="Mode manuel"):
        settings.generation_settings()
    save_settings({"mode": "openai"})
    with pytest.raises(RigAIError) as error:
        settings.generation_settings()
    assert error.value.code == "key_missing"
