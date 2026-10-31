"""Fallback index source: parse the rendered list the browser actually sees.

``Template:干员筛选`` embeds the full Cargo result set into a hidden
``<div id="filter-data">`` block, one ``<div data-char-id="...">`` per operator
(the Vue ``Widget:CharList`` then paginates it client-side at 50 per page).
This module reproduces that DOM extraction so the crawler keeps working even
if ``action=cargoquery`` is disabled or renamed.
"""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Any

from .config import API_URL, INDEX_PAGE
from .http import HttpClient
from .wikitext import to_int

#: ``data-*`` attribute -> field name used by the Cargo based index.
ATTRIBUTE_MAP = {
    "data-char-id": "charId",
    "data-sortid": "charIndex",
    "data-zh": "page",
    "data-rarity": "rarity",
    "data-profession": "profession",
    "data-subprofession": "subProfession",
    "data-position": "position",
    "data-tag": "tag",
    "data-nation": "nation",
    "data-group": "org",
    "data-team": "team",
    "data-logo": "logo",
    "data-id": "eid",
    "data-en": "en",
    "data-ja": "jp",
    "data-hp": "hp",
    "data-atk": "atk",
    "data-def": "def",
    "data-res": "res",
    "data-re-deploy": "reDeploy",
    "data-cost": "cost",
    "data-block": "block",
    "data-interval": "atkSpeed",
    "data-potential": "potential",
    "data-trust": "trust",
    "data-ingame-faction": "ingameFaction",
    "data-ingame-hidden-faction": "hiddenFaction",
    "data-birth-place": "birthPlace",
    "data-race": "race",
    "data-sex": "sex",
    "data-phy": "phy",
    "data-flex": "flex",
    "data-tolerance": "tolerance",
    "data-plan": "plan",
    "data-skill": "skillRating",
    "data-adapt": "adapt",
    "data-obtain-method": "obtain",
}

_INT_FIELDS = {"rarity", "charIndex", "hp", "atk", "def", "res", "cost", "block"}


class _CardParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cards: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "div":
            return
        attributes = {key: (value or "") for key, value in attrs}
        if "data-char-id" not in attributes:
            return
        card: dict[str, str] = {}
        for attribute, field in ATTRIBUTE_MAP.items():
            if attribute in attributes:
                card[field] = attributes[attribute]
        self.cards.append(card)


class HtmlIndexSource:
    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def fetch_rendered_html(self) -> str:
        payload = self.client.get_json(
            API_URL,
            {
                "action": "parse",
                "page": INDEX_PAGE,
                "prop": "text",
                "format": "json",
                "formatversion": "2",
            },
        )
        if payload.get("error"):
            error = payload["error"]
            raise RuntimeError(f"{error.get('code')}: {error.get('info')}")
        return payload["parse"]["text"]

    def fetch_index(self) -> list[dict[str, Any]]:
        parser = _CardParser()
        parser.feed(self.fetch_rendered_html())
        rows: list[dict[str, Any]] = []
        for card in parser.cards:
            for field in _INT_FIELDS:
                if field in card:
                    card[field] = to_int(card[field])  # type: ignore[assignment]
            rows.append(dict(card))
        return rows
