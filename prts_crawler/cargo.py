"""Cargo (Semantic MediaWiki's structured store) queries.

``Template:干员筛选`` renders the operator list with::

    {{#cargo_query:
    tables=chara,chara_data,chara_extra_info,char_obtain
    |join on=chara._pageName=chara_data._pageName,...
    |where=chara.charIndex>0
    |fields=chara._pageName=干员,...
    |limit=5000
    |format=template}}

The same query is exposed over ``api.php?action=cargoquery``, which returns
clean JSON instead of the 50-per-page Vue widget output.
"""

from __future__ import annotations

from typing import Any, Iterable

from .config import API_URL, MAX_CARGO_LIMIT
from .http import HttpClient, HttpError

INDEX_TABLES = "chara,chara_data,chara_extra_info,char_obtain"
INDEX_JOIN_ON = (
    "chara._pageName=chara_data._pageName,"
    "chara._pageName=chara_extra_info._pageName,"
    "chara._pageName=char_obtain._pageName"
)
INDEX_WHERE = "chara.charIndex>0"

#: ``cargo_field=alias`` pairs, matching the field list of Template:干员筛选.
INDEX_FIELDS: list[tuple[str, str]] = [
    ("chara._pageName", "page"),
    ("chara.charId", "charId"),
    ("chara.charIndex", "charIndex"),
    ("chara.rarity", "rarity"),
    ("chara.profession", "profession"),
    ("chara.subProfession", "subProfession"),
    ("chara.position", "position"),
    ("chara.tag", "tag"),
    ("chara.nation", "nation"),
    ("chara.org", "org"),
    ("chara.team", "team"),
    ("chara.logo", "logo"),
    ("chara.eid", "eid"),
    ("chara.en", "en"),
    ("chara.jp", "jp"),
    ("chara.feature", "feature"),
    ("chara_data.hp", "hp"),
    ("chara_data.atk", "atk"),
    ("chara_data.def", "def"),
    ("chara_data.res", "res"),
    ("chara_data.reDeploy", "reDeploy"),
    ("chara_data.cost", "cost"),
    ("chara_data.block", "block"),
    ("chara_data.atkSpeed", "atkSpeed"),
    ("chara_data.potential", "potential"),
    ("chara_data.trust", "trust"),
    ("chara_data.ingameFaction", "ingameFaction"),
    ("chara_data.hiddenFaction", "hiddenFaction"),
    ("chara_extra_info.birthPlace", "birthPlace"),
    ("chara_extra_info.race", "race"),
    ("chara_extra_info.sex", "sex"),
    ("chara_extra_info.phy", "phy"),
    ("chara_extra_info.flex", "flex"),
    ("chara_extra_info.tolerance", "tolerance"),
    ("chara_extra_info.plan", "plan"),
    ("chara_extra_info.skill", "skillRating"),
    ("chara_extra_info.adapt", "adapt"),
    ("char_obtain.obtainMethod", "obtain"),
]


def _fields_param(fields: Iterable[tuple[str, str]]) -> str:
    return ",".join(f"{column}={alias}" for column, alias in fields)


class CargoError(RuntimeError):
    pass


class CargoSource:
    """Thin wrapper around ``action=cargoquery``."""

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def query(
        self,
        tables: str,
        fields: str,
        *,
        where: str = "",
        join_on: str = "",
        order_by: str = "",
        limit: int = MAX_CARGO_LIMIT,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "action": "cargoquery",
            "format": "json",
            "formatversion": "2",
            "limit": min(limit, MAX_CARGO_LIMIT),
            "offset": offset,
            "tables": tables,
            "fields": fields,
        }
        if where:
            params["where"] = where
        if join_on:
            params["join_on"] = join_on
        if order_by:
            params["order_by"] = order_by

        payload = self.client.get_json(API_URL, params)
        if isinstance(payload, dict) and payload.get("error"):
            error = payload["error"]
            raise CargoError(f"{error.get('code')}: {error.get('info')}")
        rows = payload.get("cargoquery") or []
        return [row["title"] for row in rows]

    def query_all(
        self,
        tables: str,
        fields: str,
        *,
        where: str = "",
        join_on: str = "",
        order_by: str = "",
        page_size: int = MAX_CARGO_LIMIT,
    ) -> list[dict[str, Any]]:
        """Follow ``offset`` until a short page is returned."""
        results: list[dict[str, Any]] = []
        offset = 0
        while True:
            batch = self.query(
                tables,
                fields,
                where=where,
                join_on=join_on,
                order_by=order_by,
                limit=page_size,
                offset=offset,
            )
            results.extend(batch)
            if len(batch) < page_size:
                break
            offset += page_size
        return results

    def fetch_index(self) -> list[dict[str, Any]]:
        try:
            rows = self.query_all(
                INDEX_TABLES,
                _fields_param(INDEX_FIELDS),
                where=INDEX_WHERE,
                join_on=INDEX_JOIN_ON,
                order_by="chara.charIndex",
            )
        except (CargoError, HttpError) as exc:
            raise CargoError(f"cargo index query failed: {exc}") from exc

        unique: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = row.get("charId") or row.get("page")
            unique.setdefault(str(key), row)
        return list(unique.values())

    def fetch_table(
        self,
        table: str,
        fields: Iterable[tuple[str, str]],
        *,
        where: str = "",
        page_size: int = MAX_CARGO_LIMIT,
    ) -> list[dict[str, Any]]:
        return self.query_all(
            table,
            _fields_param(fields),
            where=where,
            page_size=page_size,
        )
