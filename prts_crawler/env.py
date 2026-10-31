"""Zero-dependency ``.env`` loader.

Implements the subset of python-dotenv this project needs:

* ``KEY=VALUE`` lines, optional ``export`` prefix
* ``#`` comments (whole-line, and trailing when the value is unquoted)
* single- or double-quoted values, with ``\\n`` / ``\\"`` / ``\\\\`` escapes
* UTF-8 with optional BOM, CRLF safe

Precedence, highest first:

1. variables already set in the real environment
2. values from the ``.env`` file
3. built-in defaults in :mod:`prts_crawler.config`

so a CI job can override anything with a plain environment variable.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

ENV_FILENAME = ".env"

#: Point this at an explicit file to skip auto-discovery.
ENV_FILE_VAR = "PRTS_ENV_FILE"

#: How many parent directories to scan when looking for the file.
_SEARCH_DEPTH = 6

_LINE_RE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_.]*)\s*=\s*(.*)$")
_INLINE_COMMENT_RE = re.compile(r"\s+#")
_TRUTHY = {"1", "true", "yes", "on", "y", "t"}
_FALSY = {"0", "false", "no", "off", "n", "f", ""}


def parse_dotenv(text: str) -> dict[str, str]:
    """Parse ``.env`` content into a plain dict (later keys win)."""
    values: dict[str, str] = {}
    for raw_line in text.lstrip("\ufeff").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _LINE_RE.match(line)
        if not match:
            continue
        key, raw_value = match.groups()
        values[key] = _parse_value(raw_value)
    return values


def _parse_value(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""

    quote = raw[0]
    if quote in {'"', "'"}:
        end = raw.rfind(quote)
        if end > 0:
            inner = raw[1:end]
            if quote == '"':
                inner = (
                    inner.replace("\\n", "\n")
                    .replace('\\"', '"')
                    .replace("\\\\", "\\")
                )
            return inner

    comment = _INLINE_COMMENT_RE.search(raw)
    if comment:
        raw = raw[: comment.start()]
    return raw.strip()


def _search_candidates(start: Path) -> list[Path]:
    candidates: list[Path] = []
    current = start.resolve()
    candidates.append(current / ENV_FILENAME)
    for _ in range(_SEARCH_DEPTH):
        if current.parent == current:
            break
        current = current.parent
        candidates.append(current / ENV_FILENAME)
    # Editable installs run with an unrelated cwd; still find the project file.
    candidates.append(Path(__file__).resolve().parent.parent / ENV_FILENAME)
    return candidates


def find_dotenv(start: Path | str | None = None) -> Path | None:
    """Locate the ``.env`` file: ``PRTS_ENV_FILE``, then cwd upward, then repo root."""
    explicit = os.environ.get(ENV_FILE_VAR)
    if explicit:
        candidate = Path(explicit).expanduser()
        return candidate if candidate.is_file() else None

    base = Path.cwd() if start is None else Path(start)
    for candidate in _search_candidates(base):
        if candidate.is_file():
            return candidate
    return None


def load_dotenv(
    path: Path | str | None = None,
    *,
    override: bool = False,
) -> Path | None:
    """Merge a ``.env`` file into ``os.environ``.

    Returns the file that was loaded, or ``None`` when nothing was found.
    """
    target = Path(path).expanduser() if path is not None else find_dotenv()
    if target is None or not target.is_file():
        return None

    text = target.read_text(encoding="utf-8-sig", errors="replace")
    for key, value in parse_dotenv(text).items():
        if override or key not in os.environ:
            os.environ[key] = value
    return target


def env_str(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return default if value is None or value.strip() == "" else value.strip()


def env_int(name: str, default: int = 0) -> int:
    raw = env_str(name)
    try:
        return int(raw)
    except ValueError:
        return default


def env_float(name: str, default: float = 0.0) -> float:
    raw = env_str(name)
    try:
        return float(raw)
    except ValueError:
        return default


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    normalized = raw.strip().lower()
    if normalized in _TRUTHY:
        return True
    if normalized in _FALSY:
        return False
    return default
