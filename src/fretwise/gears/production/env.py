import os
import re
from pathlib import Path

_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def load_project_env(*base_dirs, override=False):
    seen = set()
    paths = []
    for base_dir in base_dirs:
        if not base_dir:
            continue
        base = Path(base_dir)
        for name in (".env", ".env.txt", ".env.local"):
            path = base / name
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                paths.append(path)
    return load_env_files(paths, override=override)


def load_env_files(paths, override=False):
    loaded = {}
    original_env = set(os.environ)
    for path in paths:
        path = Path(path)
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8-sig") as f:
            for line in f:
                parsed = _parse_env_line(line)
                if parsed is None:
                    continue
                key, value = parsed
                if not override and key in original_env:
                    continue
                os.environ[key] = value
                loaded[key] = value
    return loaded


def _parse_env_line(line):
    text = line.strip()
    if not text or text.startswith("#"):
        return None
    if text.startswith("export "):
        text = text[7:].lstrip()
    if "=" not in text:
        return None
    key, value = text.split("=", 1)
    key = key.strip()
    if not _ENV_KEY_RE.match(key):
        return None
    return key, _parse_env_value(value)


def _parse_env_value(value):
    value = value.strip()
    if not value:
        return ""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        quote = value[0]
        value = value[1:-1]
        if quote == '"':
            return value.encode("utf-8").decode("unicode_escape")
        return value
    return _strip_inline_comment(value).strip()


def _strip_inline_comment(value):
    in_single = False
    in_double = False
    escaped = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if char == "#" and not in_single and not in_double:
            if index == 0 or value[index - 1].isspace():
                return value[:index]
    return value
