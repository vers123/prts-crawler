"""Render the dataset as human readable Markdown / HTML (no dependencies).

Two views, different jobs:

* **Markdown** — compact and diff-friendly. A 434-row overview table plus one
  list item per operator (skill and talent names only), so a re-crawl shows up
  as a reviewable ``git diff`` instead of a 660 KB blob.
* **HTML** — the pretty one. Single self-contained file, inline CSS/JS, avatar
  images, rarity colours, client-side search and ``<details>`` folding. Meant
  for browsing, handing over, and printing to PDF.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

STAR = "★"
RARITY_COLOR = {
    1: "#9f9f9f",
    2: "#7fc441",
    3: "#4b9fe0",
    4: "#a06bd4",
    5: "#e6b422",
    6: "#f07c2b",
}

FORMAT_CHOICES = ("md", "html", "both", "none")


def resolve_formats(value: str) -> list[str]:
    """``md`` / ``html`` / ``both`` / ``none`` -> concrete list of formats."""
    normalized = (value or "").strip().lower()
    if normalized in {"", "none", "off", "0"}:
        return []
    if normalized == "both":
        return ["md", "html"]
    if normalized in {"md", "markdown"}:
        return ["md"]
    if normalized in {"html", "htm"}:
        return ["html"]
    raise ValueError(f"未知的导出格式: {value!r}（可选 md/html/both/none）")


def _stars(rarity: int | None) -> str:
    return STAR * rarity if rarity else "?"


def _clean(value: Any) -> str:
    """Collapse newlines so a value survives a single Markdown table cell."""
    return " ".join(str(value if value is not None else "").split())


def _md_escape(value: Any) -> str:
    return _clean(value).replace("|", "\\|")


def _html_escape(value: Any) -> str:
    return html.escape(_clean(value), quote=True)


# ----------------------------------------------------------------- markdown
def render_markdown(operators: Sequence[dict], meta: dict | None = None) -> str:
    meta = meta or {}
    count = len(operators)
    fetched = meta.get("fetchedAt", "")

    lines: list[str] = [
        "# PRTS 干员一览",
        "",
        f"共 **{count}** 名干员" + (f" · 数据快照 {fetched}" if fetched else ""),
        "",
        "> 本文件由 `prts-crawler export` 生成，适合放入仓库做版本对比。",
        "> 需要带图、可搜索的浏览版，请看同目录的 `operators.html`。",
        "",
        "## 总览",
        "",
        "| # | 名称 | 星级 | 职业 | 分支 | 生命 | 攻击 | 防御 | 法抗 | 费用 | 阻挡 | 标签 |",
        "| ---: | --- | :---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]

    for op in operators:
        attrs = op.get("attributes") or {}
        lines.append(
            "| {idx} | {name} | {stars} | {prof} | {sub} | {hp} | {atk} | {defn} "
            "| {res} | {cost} | {block} | {tags} |".format(
                idx=op.get("charIndex") or "",
                name=_md_escape(op.get("name")),
                stars=_stars(op.get("rarity")),
                prof=_md_escape(op.get("profession")),
                sub=_md_escape(op.get("subProfession")),
                hp=attrs.get("hp", ""),
                atk=attrs.get("atk", ""),
                defn=attrs.get("def", ""),
                res=attrs.get("res", ""),
                cost=attrs.get("cost", ""),
                block=attrs.get("block", ""),
                tags=_md_escape("、".join(op.get("tags") or [])),
            )
        )

    grouped: dict[str, list[dict]] = {}
    for op in operators:
        grouped.setdefault(op.get("profession") or "未分类", []).append(op)

    lines += ["", "## 按职业", ""]
    for profession in sorted(grouped, key=lambda key: (-len(grouped[key]), key)):
        members = grouped[profession]
        lines.append(f"### {profession}（{len(members)}）")
        lines.append("")
        for op in members:
            skills = " / ".join(s.get("name") or "" for s in op.get("skills") or [])
            talents = " / ".join(t.get("name") or "" for t in op.get("talents") or [])
            parts = [f"- **{_clean(op.get('name'))}** {_stars(op.get('rarity'))}"]
            if op.get("subProfession"):
                parts.append(f"{_clean(op['subProfession'])}")
            if skills:
                parts.append(f"技能：{skills}")
            if talents:
                parts.append(f"天赋：{talents}")
            lines.append(" · ".join(parts))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------- html
_CSS = """
:root{--bg:#12141a;--card:#1b1e26;--fg:#e8eaf0;--dim:#9aa3b2;--line:#2c313d;--accent:#6cb6ff}
*{box-sizing:border-box}
body{margin:0;padding:28px;background:var(--bg);color:var(--fg);
  font:14px/1.65 "Segoe UI","Microsoft YaHei",system-ui,sans-serif}
h1{margin:0 0 4px;font-size:24px}
.sub{color:var(--dim);font-size:13px}
.bar{position:sticky;top:0;z-index:9;background:var(--bg);padding:12px 0 14px;
  display:flex;align-items:center;gap:12px;flex-wrap:wrap}
input{flex:1 1 320px;max-width:440px;padding:9px 12px;border-radius:8px;
  border:1px solid var(--line);background:var(--card);color:var(--fg);font-size:14px}
.grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fill,minmax(240px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
  padding:12px;display:flex;gap:12px}
.card img.avatar{width:64px;height:64px;border-radius:8px;flex:none;
  background:#0b0d12;object-fit:cover}
.card:has(details[open]){grid-column:1/-1}
.name{font-weight:600;font-size:15px}
.stars{letter-spacing:1px;font-size:12px}
.meta{color:var(--dim);font-size:12px}
.stats{display:grid;grid-template-columns:repeat(3,auto);gap:2px 12px;
  margin-top:6px;font-size:12px;color:var(--dim)}
.stats b{color:var(--fg);font-weight:600}
details{margin-top:8px}
summary{cursor:pointer;color:var(--accent);font-size:12px;outline:none}
table{border-collapse:collapse;width:100%;margin-top:6px;font-size:12px}
th,td{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left;vertical-align:top}
th{color:var(--dim);font-weight:500;white-space:nowrap}
td.num{text-align:right;white-space:nowrap}
.tag{display:inline-block;padding:1px 7px;margin:2px 4px 0 0;border-radius:99px;
  background:#242938;color:#b8c2d4;font-size:11px}
.empty{color:var(--dim);padding:24px 0}
"""

_JS = """
const q=document.getElementById('q');
const cards=[...document.querySelectorAll('.card')];
const cnt=document.getElementById('cnt');
q.addEventListener('input',()=>{
  const v=q.value.trim().toLowerCase();
  let hit=0;
  for(const c of cards){
    const ok=!v||c.dataset.search.includes(v);
    c.style.display=ok?'':'none';
    if(ok)hit++;
  }
  cnt.textContent=hit;
});
"""


def _stat_block(attrs: dict) -> str:
    cells = [
        ("生命", attrs.get("hp")),
        ("攻击", attrs.get("atk")),
        ("防御", attrs.get("def")),
        ("法抗", attrs.get("res")),
        ("费用", attrs.get("cost")),
        ("阻挡", attrs.get("block")),
    ]
    return "".join(
        f"<span>{label} <b>{_html_escape(value)}</b></span>" for label, value in cells
    )


def _table(headers: Sequence[str], rows: Iterable[Sequence[str]]) -> str:
    head = "".join(f"<th>{_html_escape(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows
    )
    return f"<table><tr>{head}</tr>{body}</table>"


def _skill_section(op: dict) -> str:
    skills = op.get("skills") or []
    if not skills:
        return ""
    rows = []
    for skill in skills:
        level7 = (skill.get("levels") or {}).get("7", {})
        mastery3 = (skill.get("mastery") or {}).get("m3", {})
        rows.append(
            (
                _html_escape(skill.get("name")),
                _html_escape(skill.get("recovery")),
                _html_escape(skill.get("activation")),
                f"<span class='num'>{_html_escape(level7.get('spCost', ''))}</span>",
                _html_escape(mastery3.get("description") or level7.get("description")),
            )
        )
    return (
        f"<details><summary>技能 {len(skills)} 个</summary>"
        + _table(("技能", "回复", "触发", "7级消耗", "专三效果"), rows)
        + "</details>"
    )


def _talent_section(op: dict) -> str:
    talents = op.get("talents") or []
    if not talents:
        return ""
    rows = [
        (
            _html_escape(talent.get("name")),
            _html_escape(talent.get("condition")),
            _html_escape(talent.get("description")),
        )
        for talent in talents
    ]
    return (
        f"<details><summary>天赋 {len(talents)} 条</summary>"
        + _table(("天赋", "解锁", "效果"), rows)
        + "</details>"
    )


def _module_section(op: dict) -> str:
    modules = op.get("modules") or []
    if not modules:
        return ""

    def last_stage(stages: dict, key: str) -> str:
        values = [v for v in (stages or {}).get(key) or [] if v is not None]
        return values[-1] if values else "—"

    rows = [
        (
            _html_escape(module.get("name")),
            _html_escape(module.get("type")),
            _html_escape(last_stage(module.get("stages") or {}, "atk")),
            _html_escape(last_stage(module.get("stages") or {}, "hp")),
        )
        for module in modules
    ]
    return (
        f"<details><summary>模组 {len(modules)} 个</summary>"
        + _table(("名称", "类型", "三阶段攻击", "三阶段生命"), rows)
        + "</details>"
    )


def _building_section(op: dict) -> str:
    skills = op.get("buildingSkills") or []
    if not skills:
        return ""
    rows = [
        (
            _html_escape(skill.get("name")),
            _html_escape(skill.get("room")),
            _html_escape(skill.get("phase")),
            _html_escape(skill.get("description")),
        )
        for skill in skills
    ]
    return (
        f"<details><summary>基建技能 {len(skills)} 个</summary>"
        + _table(("技能", "房间", "阶段", "效果"), rows)
        + "</details>"
    )


def _card(op: dict) -> str:
    attrs = op.get("attributes") or {}
    name = op.get("name") or ""
    rarity = op.get("rarity")
    color = RARITY_COLOR.get(rarity, "#9f9f9f")
    tags = "".join(f'<span class="tag">{_html_escape(t)}</span>' for t in op.get("tags") or [])
    search = " ".join(
        [
            str(name),
            str(op.get("nameEn") or ""),
            str(op.get("nameJp") or ""),
            str(op.get("profession") or ""),
            str(op.get("subProfession") or ""),
            str(op.get("position") or ""),
            " ".join(op.get("tags") or []),
        ]
    ).lower()

    sections = "".join(
        (
            _skill_section(op),
            _talent_section(op),
            _module_section(op),
            _building_section(op),
        )
    )

    return (
        f'\n<div class="card" data-search="{_html_escape(search)}">\n'
        f'  <img class="avatar" src="../media/avatars/{_html_escape(name)}.png" '
        f'alt="{_html_escape(name)}" loading="lazy">\n'
        f'  <div style="min-width:0;flex:1">\n'
        f'    <div class="name">{_html_escape(name)}</div>\n'
        f'    <div class="stars" style="color:{color}">{_stars(rarity)}</div>\n'
        f'    <div class="meta">{_html_escape(op.get("profession"))} / '
        f'{_html_escape(op.get("subProfession"))} · {_html_escape(op.get("position"))}</div>\n'
        f"    {tags}\n"
        f'    <div class="stats">{_stat_block(attrs)}</div>\n'
        f"    {sections}\n"
        f"  </div>\n"
        f"</div>"
    )


def render_html(operators: Sequence[dict], meta: dict | None = None) -> str:
    meta = meta or {}
    fetched = meta.get("fetchedAt", "")
    subtitle = f"共 {len(operators)} 名干员" + (f" · 数据快照 {fetched}" if fetched else "")
    cards = "".join(_card(op) for op in operators)
    grid = f'<div class="grid">{cards}</div>' if cards else '<p class="empty">没有数据</p>'

    return (
        "<!doctype html>\n"
        '<html lang="zh-CN"><head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f"<title>PRTS 干员一览 · {len(operators)} 名</title>\n"
        f"<style>{_CSS}</style></head>\n"
        "<body>\n"
        "<h1>PRTS 干员一览</h1>\n"
        f'<div class="sub">{_html_escape(subtitle)}</div>\n'
        '<div class="bar">\n'
        '  <input id="q" placeholder="搜索名称 / 职业 / 分支 / 标签…" autocomplete="off">\n'
        f'  <span class="sub">命中 <b id="cnt">{len(operators)}</b></span>\n'
        "</div>\n"
        f"{grid}\n"
        f"<script>{_JS}</script>\n"
        "</body></html>\n"
    )


# ------------------------------------------------------------------- export
def load_dataset(path: Path) -> tuple[list[dict], dict]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        return payload.get("operators", []), payload.get("meta", {})
    return payload, {}


def export(
    operators: Sequence[dict],
    out_dir: Path,
    formats: Sequence[str],
    meta: dict | None = None,
) -> list[Path]:
    """Write the requested views into ``<out_dir>/exports``."""
    written: list[Path] = []
    if not formats:
        return written

    target = Path(out_dir) / "exports"
    target.mkdir(parents=True, exist_ok=True)

    if "md" in formats:
        path = target / "operators.md"
        path.write_text(render_markdown(operators, meta), encoding="utf-8", newline="\n")
        written.append(path)
    if "html" in formats:
        path = target / "operators.html"
        path.write_text(render_html(operators, meta), encoding="utf-8", newline="\n")
        written.append(path)
    return written
