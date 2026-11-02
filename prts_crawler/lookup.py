"""Stage lookup: resolve a user-typed stage reference to a stage record.

Callers say things like ``1-7``、``7-18``、``M8-2``、``暴君``、``H7-1``，or paste
``main_01-07``. Resolution order:

1. local ``stages.json`` (exact stage id → exact code → exact name → substring)
2. PRTS search, when the local index has no match or is missing

Local matching is deliberately scored rather than boolean so callers can see
*why* a stage matched, and so an ambiguous query yields several candidates
instead of silently picking one.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from .config import API_URL
from .http import HttpClient
from .stages import parse_stage

#: Scores are ordered so any exact identifier beats every fuzzy match.
_SCORE_STAGE_ID = 100
_SCORE_PAGE = 95
_SCORE_CODE_NAME = 90
_SCORE_CODE = 85
_SCORE_NAME = 80
_SCORE_CODE_CONTAINS = 70
_SCORE_NAME_CONTAINS = 60
_SCORE_PAGE_CONTAINS = 50

_NUM_RE = re.compile(r"(\d+)")


@dataclass(frozen=True)
class StageMatch:
    stage: dict[str, Any]
    score: int
    reason: str

    @property
    def code(self) -> str:
        return str(self.stage.get("code") or "")

    @property
    def name(self) -> str:
        return str(self.stage.get("name") or "")


def natural_key(value: str) -> tuple:
    """``7-18`` sorts after ``7-2``（纯字符串排序会反过来）。"""
    parts = _NUM_RE.split(value or "")
    return tuple(int(part) if part.isdigit() else part.casefold() for part in parts)


def _normalize(value: str) -> str:
    return " ".join((value or "").split()).casefold()


def load_stages(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        return payload.get("stages", [])
    return payload


def search_local(stages: Iterable[dict[str, Any]], query: str) -> list[StageMatch]:
    """Rank local stages against *query*; empty list when nothing matches."""
    q = _normalize(query)
    if not q:
        return []

    matches: list[StageMatch] = []
    for stage in stages:
        code = _normalize(str(stage.get("code") or ""))
        name = _normalize(str(stage.get("name") or ""))
        page = _normalize(str(stage.get("page") or ""))
        stage_id = _normalize(str(stage.get("stageId") or ""))

        score = 0
        reason = ""
        if stage_id and q == stage_id:
            score, reason = _SCORE_STAGE_ID, "关卡 id 精确匹配"
        elif page and q == page:
            score, reason = _SCORE_PAGE, "页面标题精确匹配"
        elif code and q == f"{code} {name}":
            score, reason = _SCORE_CODE_NAME, "代号 + 名称精确匹配"
        elif code and q == code:
            score, reason = _SCORE_CODE, "关卡代号精确匹配"
        elif name and q == name:
            score, reason = _SCORE_NAME, "关卡名精确匹配"
        elif code and q in code:
            score, reason = _SCORE_CODE_CONTAINS, "关卡代号包含查询"
        elif name and q in name:
            score, reason = _SCORE_NAME_CONTAINS, "关卡名包含查询"
        elif page and q in page:
            score, reason = _SCORE_PAGE_CONTAINS, "页面标题包含查询"

        if score:
            matches.append(StageMatch(stage, score, reason))

    matches.sort(
        key=lambda match: (-match.score, natural_key(match.code), match.name)
    )
    return matches


def remote_search(client: HttpClient, query: str, *, limit: int = 10) -> list[str]:
    """Ask the wiki for pages matching *query*（本地没有时的兜底）。"""
    payload = client.get_json(
        API_URL,
        {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "list": "search",
            "srsearch": query,
            "srnamespace": "0",
            "srlimit": str(limit),
        },
    )
    if payload.get("error"):
        error = payload["error"]
        raise RuntimeError(f"{error.get('code')}: {error.get('info')}")
    return [
        item["title"] for item in payload.get("query", {}).get("search", [])
    ]


def fetch_remote_stage(
    client: HttpClient, titles: Sequence[str]
) -> list[dict[str, Any]]:
    """Fetch and parse candidate titles; unparsable pages are skipped."""
    from .detail import WikitextSource

    if not titles:
        return []
    texts = WikitextSource(client).fetch_many(list(titles), workers=1)
    stages: list[dict[str, Any]] = []
    for title in titles:
        text = texts.get(title)
        if not text:
            continue
        stage = parse_stage(title, text)
        if stage is None:
            continue
        stage["key"] = stage.get("stageId") or stage.get("code") or title
        stage["source"] = "remote"
        stages.append(stage)
    return stages


def describe_stage(stage: dict[str, Any]) -> str:
    """Human readable summary used by the CLI."""

    def value(key: str) -> Any:
        raw = stage.get(key)
        return "-" if raw is None or raw == "" else raw

    lines = [
        f"{stage.get('code') or '?'} {stage.get('name') or ''}".strip(),
        f"  id={value('stageId')}  页面={stage.get('page')}",
        f"  类型={value('type')}  区域={value('area')}  推荐等级={value('recommendedLevel')}",
        f"  部署上限={value('deployLimit')}  初始COST={value('initialCost')}"
        f"  COST上限={value('costLimit')}  目标点耐久={value('lifePoints')}",
        f"  敌人数量={value('enemyCount')}  地图={value('mapSize')}"
        f"  最短用时={value('fastestTime')}",
        f"  消耗={value('sanity')}  演习={value('drillSanity')}"
        f"  剧情关={'是' if stage.get('storyOnly') else '否'}",
    ]
    description = (stage.get("description") or "").replace("\n", " / ")
    if description:
        lines.append(f"  机制：{description}")

    enemies = stage.get("enemies") or []
    if enemies:
        total = sum((group.get("count") or 0) for group in enemies)
        listed = "、".join(
            f"{group['name']}×{group['count']}" if group.get("count") else group["name"]
            for group in enemies
        )
        lines.append(f"  敌人（{len(enemies)} 种 / 共 {total}）：{listed}")

    devices = stage.get("devices") or []
    if devices:
        rendered = [
            f"{d['name']}(Lv{d['level']})" if d.get("level") is not None else d["name"]
            for d in devices
        ]
        lines.append("  装置：" + "、".join(rendered))

    challenge = stage.get("challenge")
    if challenge:
        condition = (challenge.get("description") or "").replace("\n", " / ")
        lines.append(f"  突袭：{challenge.get('difficulty')}  {condition}")
        if challenge.get("intel"):
            lines.append(f"    情报：{challenge['intel']}")

    return "\n".join(lines)
