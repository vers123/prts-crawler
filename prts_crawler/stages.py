"""Stage and enemy data from PRTS wikitext.

Stage pages are structured templates rather than tables::

    {{普通关卡信息|关卡代号=1-7|关卡id=main_01-07|部署上限=8|初始COST=10
      |目标点耐久=10|敌人数量=41|地图大小=11×7|推荐等级=LV.10|关卡描述=...}}
    {{突袭关卡信息|...}}          # 同一页面的高难变体
    {{敌方情报|敌人1=暴徒|敌人1数量=4|敌人1级别=0|...}}
    {{关卡装置|装置名称=震撼装置|装置等级=10|装置技能=EMP爆炸}}

Enemy pages use their own pair::

    {{敌人信息/common2|id=53|名称=暴徒|地位级别=普通|伤害类型=物理|...}}
    {{敌人信息/levelcontent|index=0|最大生命值=1700|攻击力=250|...}}

Both are read with the same batched ``action=query&prop=revisions`` call used for
operators, then parsed by :mod:`prts_crawler.wikitext`.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from .config import API_URL
from .http import HttpClient
from .wikitext import Template, find_templates, split_list, strip_markup, to_int

#: Category per crawl scope. ``all`` is the superset that covers main + event.
SCOPE_CATEGORIES: dict[str, list[str]] = {
    "main": ["主线关卡"],
    "event": ["活动关卡"],
    "all": ["普通难度关卡"],
}

SCOPE_CHOICES = tuple(SCOPE_CATEGORIES)

#: ``敌人信息/levelcontent`` fields that are plain integers.
_ENEMY_INT_FIELDS = {
    "index": "level",
    "数量": "count",
    "最大生命值": "hp",
    "攻击力": "atk",
    "防御力": "def",
    "法术抗性": "res",
    "移动速度": "moveSpeed",
    "攻击速度": "attackSpeed",
    "攻击间隔": "attackInterval",
    "生命恢复速度": "hpRecovery",
    "sp恢复速度": "spRecovery",
    "重量等级": "weight",
    "损伤抵抗": "damageResist",
    "元素抗性": "elementResist",
    "基础嘲讽等级": "tauntLevel",
}

#: Resistance fields on ``敌人信息/levelcontent``.
_RESIST_FIELDS = {
    "眩晕抗性": "stun",
    "沉默抗性": "silence",
    "沉睡抗性": "sleep",
    "冻结抗性": "freeze",
    "浮空抗性": "levitate",
    "战栗抗性": "fear",
    "恐惧抗性": "terror",
    "麻痹抗性": "paralysis",
    "诱导抗性": "induce",
    "传送抗性": "teleport",
    "缚地抗性": "root",
}


def resolve_scope(scope: str) -> list[str]:
    """``main`` / ``event`` / ``all`` -> category names."""
    key = (scope or "main").strip().lower()
    if key not in SCOPE_CATEGORIES:
        raise ValueError(f"未知的关卡范围: {scope!r}（可选 {'/'.join(SCOPE_CHOICES)}）")
    return SCOPE_CATEGORIES[key]


def _first(text: str, *names: str) -> Template | None:
    for name in names:
        found = find_templates(text, name)
        if found:
            return found[0]
    return None


def _all(text: str, *names: str) -> list[Template]:
    collected: list[Template] = []
    seen: set[str] = set()
    for name in names:
        for template in find_templates(text, name):
            if template.raw not in seen:
                seen.add(template.raw)
                collected.append(template)
    return collected


def list_category_members(
    client: HttpClient,
    category: str,
    *,
    limit: int | None = None,
) -> list[str]:
    """All article titles in ``分类:<category>``, following continuation."""
    titles: list[str] = []
    cont: dict[str, Any] = {}
    while True:
        params: dict[str, Any] = {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "list": "categorymembers",
            "cmtitle": f"分类:{category}",
            "cmnamespace": "0",
            "cmlimit": "500",
        }
        params.update(cont)
        payload = client.get_json(API_URL, params)
        if payload.get("error"):
            error = payload["error"]
            raise RuntimeError(f"{error.get('code')}: {error.get('info')}")

        for member in payload.get("query", {}).get("categorymembers", []):
            titles.append(member["title"])
            if limit and len(titles) >= limit:
                return titles

        if not payload.get("continue"):
            return titles
        cont = payload["continue"]


def _drops(raw: str) -> list[dict[str, str]]:
    """``梓兰:固定掉落,至纯源石:三星获得`` -> [{name, type}]."""
    entries: list[dict[str, str]] = []
    for item in strip_markup(raw).split(","):
        item = item.strip()
        if not item:
            continue
        name, _, kind = item.partition(":")
        entries.append({"name": name.strip(), "type": kind.strip()})
    return entries


def _stage_enemies(wikitext: str) -> list[dict[str, Any]]:
    template = _first(wikitext, "敌方情报")
    if template is None:
        return []

    by_slot: dict[int, dict[str, Any]] = {}
    for key, value in template.params.items():
        if not key.startswith("敌人"):
            continue
        rest = key[len("敌人"):]
        digits = ""
        suffix = ""
        for char in rest:
            if char.isdigit():
                digits += char
            else:
                suffix += char
        if not digits:
            continue
        slot = int(digits)
        entry = by_slot.setdefault(slot, {"name": "", "count": None, "level": None})
        if suffix == "":
            entry["name"] = strip_markup(value)
        elif suffix == "数量":
            entry["count"] = to_int(value)
        elif suffix == "级别":
            entry["level"] = to_int(value)

    return [by_slot[slot] for slot in sorted(by_slot) if by_slot[slot]["name"]]


def _stage_devices(wikitext: str) -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    for template in _all(wikitext, "关卡装置", "关卡装置2"):
        name = strip_markup(template.get("装置名称"))
        if not name:
            continue
        devices.append(
            {
                "name": name,
                "level": template.get_int("装置等级"),
                "skill": strip_markup(template.get("装置技能")),
            }
        )
    return devices


def _common_stage_fields(template: Template) -> dict[str, Any]:
    return {
        "type": strip_markup(template.get("关卡类型")),
        "difficulty": strip_markup(template.get("关卡难度")),
        "area": strip_markup(template.get("所属区域")),
        "unlock": strip_markup(template.get("解锁条件")),
        "recommendedLevel": strip_markup(template.get("推荐等级")),
        "deployLimit": template.get_int("部署上限"),
        "initialCost": template.get_int("初始COST"),
        "costLimit": template.get_int("COST上限"),
        "lifePoints": template.get_int("目标点耐久"),
        "enemyCount": template.get_int("敌人数量"),
        "mapSize": strip_markup(template.get("地图大小")),
        "fastestTime": strip_markup(template.get("最短用时")),
        "description": strip_markup(template.get("关卡描述")),
        "sanity": template.get_int("作战消耗"),
        "drillSanity": template.get_int("演习消耗"),
        "drops": {
            "first": _drops(template.get("首次掉落")),
            "normal": _drops(template.get("常规掉落")),
            "extra": split_list(strip_markup(template.get("额外物资"))),
        },
        "intel": strip_markup(template.get("情报")),
        "isBattle": strip_markup(template.get("战斗关卡")).lower() not in {"false", "no", "0"},
    }


def parse_stage(page: str, wikitext: str) -> dict[str, Any] | None:
    """Parse one stage page, or ``None`` when it holds no stage template."""
    normal = _first(wikitext, "普通关卡信息", "关卡信息")
    challenge = _first(wikitext, "突袭关卡信息")
    if normal is None and challenge is None:
        return None

    base = normal or challenge
    assert base is not None

    stage: dict[str, Any] = {
        "page": page,
        "stageId": strip_markup(base.get("关卡id")),
        "code": strip_markup(base.get("关卡代号")),
        "name": strip_markup(base.get("关卡名")),
        **_common_stage_fields(base),
        "enemies": _stage_enemies(wikitext),
        "devices": _stage_devices(wikitext),
        "challenge": _common_stage_fields(challenge) if challenge is not None else None,
    }
    # 剧情关（无战斗）没有敌人表与部署上限，与「解析失败」要区分开。
    # 页面显式声明 ``战斗关卡=false`` 时以它为准，否则退回「无敌人且无消耗」的启发式。
    if base.has("战斗关卡"):
        stage["storyOnly"] = not stage["isBattle"]
    else:
        stage["storyOnly"] = not stage["enemies"] and not stage.get("sanity")
    return stage


def parse_enemy(page: str, wikitext: str) -> dict[str, Any] | None:
    """Parse one enemy page; ``None`` when it is not an enemy record."""
    common = _first(wikitext, "敌人信息/common2", "敌人信息/common")
    levels = _all(wikitext, "敌人信息/levelcontent")
    if common is None and not levels:
        return None

    enemy: dict[str, Any] = {
        "page": page,
        "name": strip_markup((common or levels[0]).get("名称")) or page,
        "internalId": (common.get_int("id") if common is not None else None),
        "index": (common.get_int("index") if common is not None else None),
        "rank": strip_markup(common.get("地位级别")) if common is not None else "",
        "description": strip_markup(common.get("描述")) if common is not None else "",
        "damageType": strip_markup(common.get("伤害类型")) if common is not None else "",
        "attackMode": strip_markup(common.get("攻击方式")) if common is not None else "",
        "moveMode": strip_markup(common.get("行动方式")) if common is not None else "",
        "debut": strip_markup(common.get("登场活动")) if common is not None else "",
        "levels": [],
    }

    for level in levels:
        record: dict[str, Any] = {"title": strip_markup(level.get("地位"))}
        for source, target in _ENEMY_INT_FIELDS.items():
            if level.has(source):
                record[target] = to_int(level.get(source))
        if level.has("攻击范围半径"):
            record["attackRange"] = strip_markup(level.get("攻击范围半径"))
        record["description"] = strip_markup(level.get("描述"))
        record["resistances"] = {
            target: strip_markup(level.get(source))
            for source, target in _RESIST_FIELDS.items()
            if level.has(source)
        }
        enemy["levels"].append(record)

    return enemy


def stage_key(stage: dict[str, Any]) -> str:
    """Stable identifier: prefer the in-game id, fall back to code + name."""
    for candidate in (stage.get("stageId"), stage.get("code")):
        if candidate:
            return str(candidate)
    return str(stage.get("page") or "unknown")


def referenced_enemies(stages: Iterable[dict[str, Any]]) -> list[str]:
    """Distinct enemy names referenced by the given stages, in first-seen order."""
    seen: dict[str, None] = {}
    for stage in stages:
        for group in stage.get("enemies") or []:
            name = group.get("name")
            if name and name not in seen:
                seen[name] = None
    return list(seen)
