"""Turn raw roster recognition into a verified, reviewed operator list.

Recognition itself is done by an LLM reading screenshots (see the project plan);
this module is the deterministic half of that step:

* match each recognised name against the crawled PRTS dataset
  (exact name → exact foreign name → exact Japanese name → normalised name),
* flag duplicates coming from overlapping screenshots,
* check the reported level/elite against the real per-phase level caps that the
  crawler already stored, so a misread "Lv90 E1" cannot slip through,
* render the confirmed Markdown roster.

Nothing is written until the caller passes ``--write``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

ELITE_LABELS = {0: "精英0", 1: "精英1", 2: "精英2"}

_SPACE_RE = re.compile(r"[\s\u00a0]+")
_PUNCT_RE = re.compile(r"[·・\-—_·]+")

_SCORE_NAME = 100
_SCORE_NAME_EN = 95
_SCORE_NAME_JP = 90
_SCORE_NORMALIZED = 85
_SCORE_CONTAINS = 60


@dataclass
class Entry:
    """One recognised card."""

    name: str
    level: int | None = None
    elite: int | None = None
    confidence: str = "high"
    screenshot: str = ""
    note: str = ""


@dataclass
class Resolution:
    entry: Entry
    operator: dict[str, Any] | None = None
    method: str = ""
    score: int = 0
    #: 需要用户确认或修正的问题
    issues: list[str] = field(default_factory=list)
    #: 已解释清楚的情况（推定、滚动重叠造成的重复）
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.operator is not None and not self.issues

    @property
    def display_name(self) -> str:
        return str((self.operator or {}).get("name") or self.entry.name)


def normalize_name(value: str) -> str:
    """Fold spacing and separator variants so ``凯尔希 思衡托`` still matches."""
    text = _SPACE_RE.sub("", value or "")
    return _PUNCT_RE.sub("", text).casefold()


def load_entries(path: Path) -> tuple[list[Entry], dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    raw_entries = payload.get("entries", payload) if isinstance(payload, dict) else payload
    meta = payload.get("meta", {}) if isinstance(payload, dict) else {}

    entries: list[Entry] = []
    for item in raw_entries:
        if isinstance(item, str):
            entries.append(Entry(name=item))
            continue
        entries.append(
            Entry(
                name=str(item.get("name") or "").strip(),
                level=_as_int(item.get("level")),
                elite=_as_int(item.get("elite")),
                confidence=str(item.get("confidence") or "high").lower(),
                screenshot=str(item.get("screenshot") or ""),
                note=str(item.get("note") or ""),
            )
        )
    return entries, meta


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def load_operators(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        return payload.get("operators", [])
    return payload


def match_operator(name: str, operators: Iterable[dict[str, Any]]) -> tuple[dict[str, Any] | None, str, int]:
    """Best PRTS operator for *name*, with the matching method and its score."""
    target = (name or "").strip()
    if not target:
        return None, "", 0
    folded = target.casefold()
    normalised = normalize_name(target)

    best: tuple[dict[str, Any] | None, str, int] = (None, "", 0)
    for operator in operators:
        candidates = [
            (str(operator.get("name") or ""), _SCORE_NAME, "名称精确匹配"),
            (str(operator.get("nameEn") or ""), _SCORE_NAME_EN, "外文名精确匹配"),
            (str(operator.get("nameJp") or ""), _SCORE_NAME_JP, "日文名精确匹配"),
        ]
        for value, score, method in candidates:
            if value and value.casefold() == folded and score > best[2]:
                best = (operator, method, score)

        if best[2] >= _SCORE_NORMALIZED:
            continue
        if normalised and normalize_name(str(operator.get("name") or "")) == normalised:
            best = (operator, "名称归一化匹配", _SCORE_NORMALIZED)
            continue
        if normalised and normalised in normalize_name(str(operator.get("name") or "")):
            if _SCORE_CONTAINS > best[2]:
                best = (operator, "名称包含匹配", _SCORE_CONTAINS)
    return best


def phase_caps(operator: dict[str, Any]) -> dict[int, int]:
    """``{elite: maxLevel}`` from the crawled ``phases`` array."""
    caps: dict[int, int] = {}
    for phase in operator.get("phases") or []:
        elite = _as_int(phase.get("elite"))
        max_level = _as_int(phase.get("maxLevel"))
        if elite is not None and max_level is not None:
            caps[elite] = max_level
    return caps


def max_elite(operator: dict[str, Any]) -> int:
    caps = phase_caps(operator)
    return max(caps) if caps else 0


def infer_elite(operator: dict[str, Any], level: int) -> tuple[int | None, list[int]]:
    """Elite levels compatible with *level*.

    Returns ``(elite, candidates)``: when only one elite allows that level the
    answer is definite; otherwise ``elite`` is ``None`` and ``candidates`` lists
    every possibility, so callers can ask instead of guessing.
    """
    caps = phase_caps(operator)
    if not caps:
        return None, []
    possible = sorted(elite for elite, cap in caps.items() if cap >= level)
    if len(possible) == 1:
        return possible[0], possible
    return None, possible


def infer_elite_by_cap(operator: dict[str, Any], level: int) -> tuple[int | None, list[int]]:
    """Like :func:`infer_elite`, but also accepts "level equals this cap".

    Players overwhelmingly park an operator at a promotion's level cap, so when
    the observed level equals exactly one candidate's cap, that candidate is the
    best explanation. Returns ``(elite, candidates)``; ``elite`` stays ``None``
    when neither the single-candidate nor the exact-cap rule applies.
    """
    caps = phase_caps(operator)
    if not caps:
        return None, []
    candidates = sorted(elite for elite, cap in caps.items() if cap >= level)
    if len(candidates) == 1:
        return candidates[0], candidates
    exact = [elite for elite in candidates if caps[elite] == level]
    if len(exact) == 1:
        return exact[0], candidates
    return None, candidates


def resolve_entries(
    entries: Sequence[Entry],
    operators: Sequence[dict[str, Any]],
) -> list[Resolution]:
    """Resolve every entry, annotate problems, and drop exact duplicates."""
    resolutions: list[Resolution] = []
    seen: dict[str, Resolution] = {}

    for entry in entries:
        operator, method, score = match_operator(entry.name, operators)
        resolution = Resolution(entry=entry, operator=operator, method=method, score=score)

        if operator is None:
            resolution.issues.append("未匹配到 PRTS 干员")
        else:
            key = str(operator.get("charId") or operator.get("name"))
            if key in seen:
                previous = seen[key]
                first_shot = previous.entry.screenshot or "首张截图"
                resolution.operator = operator
                resolution.notes.append(f"与 {first_shot} 重复（滚动重叠，已去重）")
                resolutions.append(resolution)
                continue
            seen[key] = resolution
            entry_issues, entry_notes = _check_progress(resolution)
            resolution.issues.extend(entry_issues)
            resolution.notes.extend(entry_notes)

        if entry.confidence in {"low", "medium"}:
            resolution.issues.append(f"识别置信度 {entry.confidence}")
        resolutions.append(resolution)

    return resolutions


def _check_progress(resolution: Resolution) -> tuple[list[str], list[str]]:
    """Return ``(issues, notes)`` for one resolved entry."""
    operator = resolution.operator
    assert operator is not None
    issues: list[str] = []
    notes: list[str] = []
    entry = resolution.entry

    caps = phase_caps(operator)
    if entry.level is None:
        issues.append("缺少等级")
        return issues, notes

    if entry.elite is None:
        elite, candidates = infer_elite_by_cap(operator, entry.level)
        if elite is not None:
            entry.elite = elite
            if candidates == [elite]:
                notes.append(f"精英化由等级推定（Lv{entry.level} 仅 {ELITE_LABELS[elite]} 可达）")
            else:
                notes.append(
                    f"精英化按上限推定（Lv{entry.level} 等于 {ELITE_LABELS[elite]} 上限）"
                )
        elif candidates:
            options = "、".join(ELITE_LABELS.get(item, str(item)) for item in candidates)
            issues.append(f"精英化需确认：Lv{entry.level} 可能是 {options}")
        else:
            top = max(caps.values()) if caps else 0
            issues.append(f"Lv{entry.level} 超出该干员最高等级 Lv{top}")
        return issues, notes

    top = max_elite(operator)
    if entry.elite > top:
        issues.append(
            f"精英化 {entry.elite} 超出该干员上限 {ELITE_LABELS.get(top, top)}"
        )
        return issues, notes

    cap = caps.get(entry.elite)
    if cap is not None and entry.level > cap:
        allowed = "、".join(
            f"{ELITE_LABELS.get(elite, elite)}≤Lv{value}" for elite, value in sorted(caps.items())
        )
        issues.append(f"Lv{entry.level} 超出 {ELITE_LABELS.get(entry.elite, entry.elite)} 上限 Lv{cap}（{allowed}）")
    return issues, notes


def summarize(resolutions: Sequence[Resolution]) -> dict[str, Any]:
    matched = [item for item in resolutions if item.operator is not None]
    problems = [item for item in resolutions if item.issues]
    duplicates = [item for item in resolutions if any("重复" in note for note in item.notes)]
    inferred = [item for item in resolutions if any("推定" in note for note in item.notes)]
    return {
        "total": len(resolutions),
        "matched": len(matched),
        "unique": len({str((i.operator or {}).get("charId")) for i in matched}),
        "duplicates": len(duplicates),
        "inferredElite": len(inferred),
        "withIssues": len(problems),
        "unmatched": [item.entry.name for item in resolutions if item.operator is None],
        "issueDetails": [
            f"{item.entry.name}: {'；'.join(item.issues)}" for item in problems
        ],
        "pendingElite": [
            item.entry.name for item in problems
            if any("精英化需确认" in issue for issue in item.issues)
        ],
    }


def _stars(rarity: Any) -> str:
    value = _as_int(rarity)
    return "★" * value if value else "?"


def render_markdown(
    resolutions: Sequence[Resolution],
    meta: dict[str, Any] | None = None,
) -> str:
    """Confirmed roster, one row per operator, with level and elite."""
    meta = meta or {}
    captured = meta.get("capturedAt", "")
    dataset = meta.get("dataset", "data/operators.json")

    unique: list[Resolution] = []
    seen: set[str] = set()
    for item in resolutions:
        if item.operator is None:
            continue
        key = str(item.operator.get("charId") or item.operator.get("name"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    unique.sort(
        key=lambda item: (
            -(_as_int((item.operator or {}).get("rarity")) or 0),
            str((item.operator or {}).get("profession") or ""),
            str((item.operator or {}).get("name") or ""),
        )
    )

    lines = [
        "# 我的明日方舟干员",
        "",
        "> 以截图中每张干员卡片识别，不按相似外貌合并；仅对重复出现的同名卡片去重。"
        f"星级、职业与等级上限来自 {dataset}。",
        f"> 共 {len(unique)} 名" + (f"，截图日期 {captured}" if captured else "") + "。",
        "",
        "| PRTS 头像 | 干员 | 星级 | 职业 | 等级 | 精英化 |",
        "| :---: | --- | :---: | --- | ---: | :---: |",
    ]

    for item in unique:
        operator = item.operator or {}
        name = str(operator.get("name") or "")
        lines.append(
            "| <img src=\"../../../data/media/avatars/{file}.png\" alt=\"{alt}\" width=\"48\"> "
            "| {name} | {stars} | {prof} | {level} | {elite} |".format(
                file=name,
                alt=name,
                name=name,
                stars=_stars(operator.get("rarity")),
                prof=str(operator.get("profession") or ""),
                level=f"Lv{item.entry.level}" if item.entry.level is not None else "-",
                elite=ELITE_LABELS.get(item.entry.elite, "-") if item.entry.elite is not None else "-",
            )
        )

    return "\n".join(lines) + "\n"
