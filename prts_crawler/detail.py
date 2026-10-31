"""Fetch operator page source and turn the template tree into plain data."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Iterable, Sequence

from .config import API_URL, MAX_TITLES_PER_BATCH
from .http import HttpClient
from .wikitext import Template, find_templates, split_list, strip_markup, to_int

_REDIRECT_RE = re.compile(r"^\s*#(?:REDIRECT|重定向)\s*\[\[([^\]]+)\]\]", re.IGNORECASE)
_SKILL_LEVEL_RE = re.compile(r"^技能(专精[123]|[1-9]\d?)(描述|初始|消耗|持续)$")
_BUILDING_RE = re.compile(r"^后勤技能(\d)-(\d)(.*)$")
_STAT_KEYS = ("生命上限", "攻击", "防御", "法术抗性")


class PageMissing(RuntimeError):
    pass


class WikitextSource:
    """Batched ``action=query&prop=revisions`` reader (50 titles per request)."""

    def __init__(self, client: HttpClient, batch_size: int = MAX_TITLES_PER_BATCH) -> None:
        self.client = client
        self.batch_size = max(1, min(batch_size, MAX_TITLES_PER_BATCH))

    def _fetch_batch(self, titles: Sequence[str]) -> dict[str, str]:
        payload = self.client.get_json(
            API_URL,
            {
                "action": "query",
                "format": "json",
                "formatversion": "2",
                "prop": "revisions",
                "rvslots": "main",
                "rvprop": "content",
                "redirects": "1",
                "titles": "|".join(titles),
            },
        )
        if payload.get("error"):
            error = payload["error"]
            raise RuntimeError(f"{error.get('code')}: {error.get('info')}")

        query = payload.get("query") or {}
        aliases = {}
        for entry in query.get("redirects") or []:
            aliases[entry["from"]] = entry["to"]
        for entry in query.get("normalized") or []:
            aliases.setdefault(entry["from"], entry["to"])

        pages: dict[str, str] = {}
        for page in query.get("pages") or []:
            title = page.get("title", "")
            if page.get("missing"):
                continue
            revisions = page.get("revisions") or []
            if not revisions:
                continue
            slots = revisions[0].get("slots") or {}
            main = slots.get("main") or {}
            content = main.get("content") or main.get("*") or ""
            if content:
                pages[title] = content

        resolved: dict[str, str] = {}
        for title in titles:
            final = aliases.get(title, title)
            if final in pages:
                resolved[title] = pages[final]
            elif title in pages:
                resolved[title] = pages[title]
        return resolved

    def fetch_many(self, titles: Sequence[str], workers: int = 4) -> dict[str, str]:
        batches = [
            list(titles[index : index + self.batch_size])
            for index in range(0, len(titles), self.batch_size)
        ]
        if not batches:
            return {}
        if len(batches) == 1 or workers <= 1:
            result: dict[str, str] = {}
            for batch in batches:
                result.update(self._fetch_batch(batch))
            return result

        merged: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for partial in pool.map(self._fetch_batch, batches):
                merged.update(partial)
        return merged

    def fetch_one(self, title: str) -> str:
        pages = self.fetch_many([title])
        if title not in pages:
            raise PageMissing(title)
        return pages[title]


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


def _parse_info(text: str) -> dict[str, Any]:
    template = _first(text, "CharinfoV2")
    if template is None:
        return {}
    return {
        "charId": template.get("干员id"),
        "charIndex": template.get_int("干员序号"),
        "name": strip_markup(template.get("干员名")),
        "nameJp": strip_markup(template.get("干员名jp")),
        "nameEn": strip_markup(template.get("干员外文名")),
        "rarity": template.get_int("稀有度"),
        "profession": strip_markup(template.get("职业")),
        "subProfession": strip_markup(template.get("分支")),
        "position": strip_markup(template.get("位置")),
        "tags": split_list(strip_markup(template.get("标签"))),
        "nation": strip_markup(template.get("所属国家")),
        "org": strip_markup(template.get("所属组织")),
        "team": strip_markup(template.get("所属团队")),
        "eid": strip_markup(template.get("情报编号")),
        "feature": strip_markup(template.get("特性")),
        "painter": strip_markup(template.get("画师")),
        "designer": strip_markup(template.get("原案")),
        "voiceActors": {
            "zh": strip_markup(template.get("中文配音")),
            "ja": strip_markup(template.get("日文配音")),
            "ko": strip_markup(template.get("韩文配音")),
            "en": strip_markup(template.get("英文配音")),
        },
        "elitePortrait": strip_markup(template.get("精英0介绍")),
    }


def _parse_obtain(text: str) -> dict[str, Any]:
    template = _first(text, "干员获得方式")
    if template is None:
        return {}
    return {
        "methods": split_list(strip_markup(template.get("获得方式"))),
        "coverage": strip_markup(template.get("覆盖")),
        "releaseTime": strip_markup(template.get("上线时间")),
    }


def _parse_stats(text: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    template = _first(text, "属性")
    if template is None:
        return {}, []

    stats: dict[str, Any] = {
        "redeploy": strip_markup(template.get("再部署")),
        "cost": template.get_int("部署费用"),
        "block": template.get_int("阻挡数"),
        "attackInterval": strip_markup(template.get("攻击速度")),
        "faction": strip_markup(template.get("所属势力")),
        "trustBonus": {
            "hp": template.get_int("信赖加成_生命上限", default=0),
            "atk": template.get_int("信赖加成_攻击", default=0),
            "def": template.get_int("信赖加成_防御", default=0),
        },
    }

    phases: list[dict[str, Any]] = []
    for elite in range(3):
        prefix = f"精英{elite}"
        if not any(key.startswith(prefix + "_") for key in template.params):
            continue
        phase: dict[str, Any] = {
            "elite": elite,
            "maxLevel": template.get_int(f"{prefix}_满级"),
            "level1": {
                "hp": template.get_int(f"{prefix}_1级_生命上限"),
                "atk": template.get_int(f"{prefix}_1级_攻击"),
                "def": template.get_int(f"{prefix}_1级_防御"),
                "res": template.get_int(f"{prefix}_1级_法术抗性"),
            },
            "max": {
                "hp": template.get_int(f"{prefix}_满级_生命上限"),
                "atk": template.get_int(f"{prefix}_满级_攻击"),
                "def": template.get_int(f"{prefix}_满级_防御"),
                "res": template.get_int(f"{prefix}_满级_法术抗性"),
            },
        }
        if template.has(f"{prefix}范围"):
            phase["range"] = strip_markup(template.get(f"{prefix}范围"))
        phases.append(phase)
    return stats, phases


def _parse_potential(text: str) -> list[dict[str, Any]]:
    template = _first(text, "属性")
    if template is None:
        return []
    types = [item.strip() for item in template.get("潜能类型").split(",") if item.strip()]
    values = [item.strip() for item in template.get("潜能").split(",") if item.strip()]
    ranks = _first(text, "潜能提升")
    descriptions = []
    if ranks is not None:
        descriptions = [
            strip_markup(ranks.get(f"潜能{index}")) for index in range(2, 7)
        ]
    entries: list[dict[str, Any]] = []
    for index, value in enumerate(values):
        entry: dict[str, Any] = {
            # 潜能 as stored in `属性` lists 潜能2..潜能6 only.
            "rank": index + 2,
            "type": types[index] if index < len(types) else "",
            "value": to_int(value, 0) if re.fullmatch(r"-?\d+", value) else value,
        }
        if index < len(descriptions) and descriptions[index]:
            entry["description"] = descriptions[index]
        entries.append(entry)
    return entries


def _parse_talents(text: str) -> list[dict[str, Any]]:
    talents: list[dict[str, Any]] = []
    for template in _all(text, "天赋列表3", "天赋列表"):
        slot_label = strip_markup(template.get("天赋"))
        slot = 1
        while template.has(f"天赋{slot}") or template.has(f"天赋{slot}效果"):
            talents.append(
                {
                    "slot": slot,
                    "label": slot_label,
                    "name": strip_markup(template.get(f"天赋{slot}")),
                    "condition": strip_markup(template.get(f"天赋{slot}条件")),
                    "description": strip_markup(template.get(f"天赋{slot}效果")),
                }
            )
            slot += 1
    return talents


def _skill_levels(template: Template) -> dict[str, dict[str, Any]]:
    levels: dict[str, dict[str, Any]] = {}
    for key, value in template.params.items():
        match = _SKILL_LEVEL_RE.match(key)
        if not match:
            continue
        stage, field_name = match.groups()
        bucket = levels.setdefault(stage, {})
        if field_name == "描述":
            bucket["description"] = strip_markup(value)
        elif field_name == "初始":
            bucket["initialSp"] = to_int(value, 0)
        elif field_name == "消耗":
            bucket["spCost"] = to_int(value, 0)
        else:
            bucket["duration"] = strip_markup(value)
    order = [str(i) for i in range(1, 10)] + ["专精1", "专精2", "专精3"]
    ordered: dict[str, dict[str, Any]] = {}
    for stage in order:
        if stage in levels:
            key = stage.replace("专精", "m")
            ordered[key] = levels[stage]
    return ordered


def _parse_skills(text: str) -> list[dict[str, Any]]:
    skills: list[dict[str, Any]] = []
    for index, template in enumerate(_all(text, "技能", "技能2"), start=1):
        levels = _skill_levels(template)
        if not levels:
            continue
        skills.append(
            {
                "index": index,
                "name": strip_markup(template.get("技能名")),
                "nameJp": strip_markup(template.get("技能名jp")),
                "nameEn": strip_markup(template.get("技能名en")),
                "recovery": strip_markup(template.get("技能类型1")),
                "activation": strip_markup(template.get("技能类型2")),
                "icon": strip_markup(template.get("技能图标")),
                "levels": levels,
                "mastery": {
                    key: value
                    for key, value in levels.items()
                    if key.startswith("m")
                },
            }
        )
    return skills


def _module_levels(template: Template) -> dict[str, list[int | None]]:
    def stages(*keys: str) -> list[int | None]:
        values: list[int | None] = []
        for key in keys:
            if template.has(key):
                values.append(to_int(template.get(key)))
            elif values:
                break
        return values

    return {
        "hp": stages("生命", "生命2", "生命3"),
        "atk": stages("攻击", "攻击2", "攻击3"),
        "def": stages("防御", "防御2", "防御3"),
        "res": stages("法术抗性", "法术抗性2", "法术抗性3"),
        "redeploy": stages("再部署", "再部署2", "再部署3"),
        "cost": stages("部署费用", "部署费用2", "部署费用3"),
        "block": stages("阻挡数", "阻挡数2", "阻挡数3"),
        "attackInterval": stages("攻击速度", "攻击速度2", "攻击速度3"),
    }


def _parse_modules(text: str) -> list[dict[str, Any]]:
    modules: list[dict[str, Any]] = []
    for index, template in enumerate(_all(text, "模组"), start=1):
        name = strip_markup(template.get("名称"))
        if not name:
            continue
        is_badge = template.has("基础证章")
        module_type = strip_markup(template.get("类型")) or strip_markup(template.get("类型图标"))
        if not module_type and is_badge:
            module_type = "基础证章"
        modules.append(
            {
                "index": index,
                "name": name,
                "type": module_type,
                "baseBadge": is_badge,
                "description": strip_markup(template.get("基础信息")),
                "unlockLevel": template.get_int("解锁等级"),
                "traitAdd": strip_markup(template.get("特性追加")),
                "trait": strip_markup(template.get("特性")),
                "talentUpgrades": {
                    "stage2": strip_markup(template.get("天赋2")),
                    "stage3": strip_markup(template.get("天赋3")),
                    "potential": strip_markup(template.get("潜能天赋2")),
                },
                "stages": _module_levels(template),
                "materials": [
                    strip_markup(template.get(key))
                    for key in ("材料消耗", "材料消耗2", "材料消耗3")
                    if template.has(key)
                ],
                "missions": [
                    strip_markup(template.get(key))
                    for key in ("任务1", "任务2", "任务3")
                    if template.has(key)
                ],
            }
        )
    return modules


def _parse_building_skills(text: str) -> list[dict[str, Any]]:
    template = _first(text, "后勤技能")
    if template is None:
        return []
    by_slot: dict[tuple[int, int], dict[str, Any]] = {}
    for key, value in template.params.items():
        match = _BUILDING_RE.match(key)
        if not match:
            continue
        slot, sub, suffix = int(match.group(1)), int(match.group(2)), match.group(3)
        entry = by_slot.setdefault(
            (slot, sub),
            {"slot": slot, "sub": sub},
        )
        if suffix == "":
            entry["name"] = strip_markup(value)
        elif suffix == "阶段":
            entry["phase"] = strip_markup(value)
        elif suffix == "等级":
            entry["level"] = strip_markup(value)
        elif suffix == "房间":
            entry["room"] = strip_markup(value)
        elif suffix == "描述":
            entry["description"] = strip_markup(value)
        elif suffix == "ID":
            entry["buffId"] = strip_markup(value)
        elif suffix == "图标":
            entry["icon"] = strip_markup(value)
    return [by_slot[key] for key in sorted(by_slot)]


def _parse_profile(text: str) -> dict[str, Any]:
    template = _first(text, "人员档案set", "人员档案设置")
    if template is None:
        return {}
    return {
        "sex": strip_markup(template.get("性别", "设定性别")),
        "combatExperience": strip_markup(template.get("战斗经验")),
        "birthPlace": strip_markup(template.get("出身地")),
        "birthday": strip_markup(template.get("生日")),
        "race": strip_markup(template.get("种族")),
        "height": strip_markup(template.get("身高")),
        "infection": strip_markup(template.get("矿石病感染情况")),
        "infected": strip_markup(template.get("是否感染者")),
        "physicalStrength": strip_markup(template.get("物理强度")),
        "mobility": strip_markup(template.get("战场机动")),
        "endurance": strip_markup(template.get("生理耐受")),
        "tactics": strip_markup(template.get("战术规划")),
        "combatSkill": strip_markup(template.get("战斗技巧")),
        "artsAdaptability": strip_markup(template.get("源石技艺适应性")),
        "originiumCrystalRate": strip_markup(template.get("体细胞与源石融合率")),
        "bloodCrystalDensity": strip_markup(template.get("血液源石结晶密度")),
    }


def _parse_description(text: str) -> dict[str, Any]:
    template = _first(text, "相关道具")
    if template is None:
        return {}
    return {
        "introduction": strip_markup(template.get("干员简介")),
        "introductionExtra": strip_markup(template.get("干员简介补充")),
        "tokenUsage": strip_markup(template.get("信物用途")),
        "tokenDescription": strip_markup(template.get("信物描述")),
    }


def parse_operator_page(page: str, wikitext: str) -> dict[str, Any]:
    redirect = _REDIRECT_RE.match(wikitext)
    if redirect:
        return {"page": page, "redirect": redirect.group(1).strip()}

    info = _parse_info(wikitext)
    stats, phases = _parse_stats(wikitext)
    return {
        "page": page,
        "info": info,
        "obtain": _parse_obtain(wikitext),
        "stats": stats,
        "phases": phases,
        "potential": _parse_potential(wikitext),
        "talents": _parse_talents(wikitext),
        "skills": _parse_skills(wikitext),
        "modules": _parse_modules(wikitext),
        "buildingSkills": _parse_building_skills(wikitext),
        "profile": _parse_profile(wikitext),
        "description": _parse_description(wikitext),
    }


def parse_many(pages: Iterable[tuple[str, str]]) -> list[dict[str, Any]]:
    return [parse_operator_page(page, text) for page, text in pages]
