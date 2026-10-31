"""Resolve and download images referenced by the operator list."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable, Sequence

from .config import API_URL, MAX_TITLES_PER_BATCH
from .http import HttpClient

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_filename(name: str) -> str:
    cleaned = _ILLEGAL.sub("_", name).strip(" .")
    return cleaned or "unnamed"


def _chunks(items: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


class MediaDownloader:
    def __init__(self, client: HttpClient, out_dir: Path) -> None:
        self.client = client
        self.out_dir = out_dir

    def resolve(self, file_titles: Sequence[str]) -> dict[str, dict[str, Any]]:
        """Map ``File:...`` titles to their ``imageinfo`` payload."""
        resolved: dict[str, dict[str, Any]] = {}
        for batch in _chunks(list(file_titles), MAX_TITLES_PER_BATCH):
            payload = self.client.get_json(
                API_URL,
                {
                    "action": "query",
                    "format": "json",
                    "formatversion": "2",
                    "prop": "imageinfo",
                    "iiprop": "url|size",
                    "titles": "|".join(batch),
                },
            )
            if payload.get("error"):
                continue
            query = payload.get("query") or {}
            aliases: dict[str, str] = {}
            for entry in query.get("normalized") or []:
                aliases[entry["from"]] = entry["to"]
            for entry in query.get("redirects") or []:
                aliases[entry["from"]] = entry["to"]
            pages = {page["title"]: page for page in query.get("pages") or []}

            for title in batch:
                final = aliases.get(title, title)
                final = aliases.get(final, final)
                page = pages.get(final)
                if not page:
                    page = pages.get(title)
                info = (page or {}).get("imageinfo") or []
                if info:
                    resolved[title] = info[0]
        return resolved

    def download(self, url: str, destination: Path, expected_size: int | None = None) -> bool:
        if destination.exists():
            if expected_size is None or destination.stat().st_size == expected_size:
                return False
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = self.client.get(url, binary=True)
        assert isinstance(payload, (bytes, bytearray))
        destination.write_bytes(bytes(payload))
        return True


def avatar_titles(names: Sequence[str]) -> list[str]:
    return [f"File:头像_{name}.png" for name in names]


def profession_icon_titles(professions: Iterable[str]) -> list[str]:
    return [f"File:图标_职业_{profession}.png" for profession in sorted(set(professions)) if profession]
