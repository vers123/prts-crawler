"""A small, dependency-free parser for the MediaWiki template syntax.

PRTS operator pages are almost entirely made of structured templates such as
``{{CharinfoV2|干员名=能天使|稀有度=6|...}}``.  Instead of scraping the rendered
HTML (which carries skin/theme noise) we read the source wikitext via
``action=query&prop=revisions`` and walk the template tree.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Iterator, Sequence

_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_BOLD_RE = re.compile(r"'{2,5}")
_SPACE_RE = re.compile(r"[ \t\u00a0]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")
_PARAM_NAME_RE = re.compile(r"^[\w\u4e00-\u9fff\u3040-\u30ff\-·．]+$")

#: Templates whose last positional argument is the human readable text.
_PASS_THROUGH = {"color", "fc", "字色", "colored", "big", "small", "ruby"}


@dataclass
class Template:
    """A single ``{{name|...}}`` invocation."""

    name: str
    params: dict[str, str] = field(default_factory=dict)
    positional: list[str] = field(default_factory=list)
    raw: str = ""

    def get(self, *keys: str, default: str = "") -> str:
        for key in keys:
            value = self.params.get(key)
            if value:
                return value.strip()
        return default

    def get_int(self, *keys: str, default: int | None = None) -> int | None:
        raw = self.get(*keys)
        return to_int(raw, default)

    def has(self, key: str) -> bool:
        return bool(self.params.get(key, "").strip())


def _find_end(text: str, start: int) -> int:
    """Index just past the ``}}`` matching the ``{{`` at *start*."""
    depth = 0
    index = start
    length = len(text)
    while index < length:
        if text.startswith("{{", index):
            depth += 1
            index += 2
        elif text.startswith("}}", index):
            depth -= 1
            index += 2
            if depth == 0:
                return index
        else:
            index += 1
    raise ValueError("unbalanced template braces")


def _split_top_level(text: str, sep: str = "|") -> list[str]:
    parts: list[str] = []
    buffer: list[str] = []
    depth_template = 0
    depth_link = 0
    index = 0
    length = len(text)
    while index < length:
        if text.startswith("{{", index):
            depth_template += 1
            buffer.append("{{")
            index += 2
        elif text.startswith("}}", index) and depth_template:
            depth_template -= 1
            buffer.append("}}")
            index += 2
        elif text.startswith("[[", index):
            depth_link += 1
            buffer.append("[[")
            index += 2
        elif text.startswith("]]", index) and depth_link:
            depth_link -= 1
            buffer.append("]]")
            index += 2
        elif text[index] == sep and depth_template == 0 and depth_link == 0:
            parts.append("".join(buffer))
            buffer = []
            index += 1
        else:
            buffer.append(text[index])
            index += 1
    parts.append("".join(buffer))
    return parts


def parse_template(raw: str) -> Template:
    if not raw.startswith("{{") or not raw.endswith("}}"):
        raise ValueError("not a template")
    body = raw[2:-2]
    parts = _split_top_level(body)
    name = parts[0].strip()
    params: dict[str, str] = {}
    positional: list[str] = []
    for part in parts[1:]:
        key, sep, value = part.partition("=")
        stripped_key = key.strip()
        if sep and _PARAM_NAME_RE.match(stripped_key):
            params[stripped_key] = value.strip()
        else:
            positional.append(part.strip())
    return Template(name=name, params=params, positional=positional, raw=raw)


def iter_templates(text: str, *, nested: bool = True) -> Iterator[Template]:
    """Yield every template found in *text*, in document order."""
    index = 0
    length = len(text)
    while index < length:
        if text.startswith("{{", index):
            end = _find_end(text, index)
            template = parse_template(text[index:end])
            yield template
            if nested:
                for value in list(template.params.values()) + template.positional:
                    if "{{" in value:
                        yield from iter_templates(value)
            index = end
        else:
            index += 1


def find_templates(text: str, names: Sequence[str] | str) -> list[Template]:
    wanted = {names} if isinstance(names, str) else set(names)
    seen: set[str] = set()
    found: list[Template] = []
    for template in iter_templates(text):
        if template.name in wanted and template.raw not in seen:
            seen.add(template.raw)
            found.append(template)
    return found


def strip_markup(text: str) -> str:
    """Flatten wikitext into plain text (links, colours, tags, entities)."""
    if not text:
        return ""
    out: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        if text.startswith("{{", index):
            end = _find_end(text, index)
            template = parse_template(text[index:end])
            if template.name in _PASS_THROUGH and template.positional:
                out.append(strip_markup(template.positional[-1]))
            elif template.name in {"#if", "#ifeq"} and template.positional:
                # {{#if:cond|then|else}} -> keep the first branch
                out.append(strip_markup(template.positional[0]))
            elif template.name.startswith("#vardefine"):
                pass
            else:
                # Unknown templates: the last positional argument is normally the
                # display text (e.g. {{术语|ba.stun|晕眩}}, {{变动数值lite|up|蓝|3}}).
                out.append(strip_markup(template.positional[-1]) if template.positional else "")
            index = end
        elif text.startswith("[[", index):
            end = text.find("]]", index)
            if end < 0:
                out.append(text[index:])
                break
            target = text[index + 2 : end]
            parts = _split_top_level(target, "|")
            label = parts[-1] if len(parts) > 1 else target
            out.append(strip_markup(label))
            index = end + 2
        else:
            out.append(text[index])
            index += 1

    value = "".join(out)
    value = _BR_RE.sub("\n", value)
    value = _TAG_RE.sub("", value)
    value = _BOLD_RE.sub("", value)
    value = html.unescape(value).replace("\u00a0", " ")
    value = _SPACE_RE.sub(" ", value)
    value = "\n".join(line.strip() for line in value.splitlines())
    value = _BLANK_LINES_RE.sub("\n\n", value)
    return value.strip()


def strip_html(text: str) -> str:
    """Clean values that Cargo stores as rendered HTML fragments."""
    if not text:
        return ""
    value = _BR_RE.sub("\n", text)
    value = _TAG_RE.sub("", value)
    value = _BOLD_RE.sub("", value)
    value = html.unescape(value).replace("\u00a0", " ")
    value = _SPACE_RE.sub(" ", value)
    value = "\n".join(line.strip() for line in value.splitlines())
    return _BLANK_LINES_RE.sub("\n\n", value).strip()


def to_int(value: str | None, default: int | None = None) -> int | None:
    if value is None:
        return default
    match = re.search(r"-?\d+", str(value))
    return int(match.group()) if match else default


def split_list(value: str, separators: str = r"[,，、\s]+") -> list[str]:
    if not value:
        return []
    return [item.strip() for item in re.split(separators, value) if item and item.strip()]
