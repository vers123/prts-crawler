"""Crawl orchestration: index -> detail pages -> merged dataset -> media."""

from __future__ import annotations

import json
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from .cargo import CargoError, CargoSource
from .config import API_URL, INDEX_PAGE, WIKI_BASE, load_settings
from .detail import WikitextSource, parse_operator_page
from .fallback import HtmlIndexSource
from .http import HttpClient
from .media import MediaDownloader, avatar_titles, profession_icon_titles, safe_filename
from .wikitext import split_list, strip_html, to_int


@dataclass
class CrawlConfig:
    out_dir: Path
    workers: int | None = None
    rate: float | None = None
    timeout: float | None = None
    retries: int | None = None
    limit: int | None = None
    refresh: bool = False
    with_media: bool | None = None
    keep_wikitext: bool = False
    verbose: bool = False


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _split_potential(raw: str) -> list[dict[str, Any]]:
    """``cost,atk,re_deploy`-1,12,-5`` -> [{type, value}, ...]."""
    if not raw or "`" not in raw:
        return []
    types_part, values_part = raw.split("`", 1)
    if not values_part.strip():
        return []
    types = [item.strip() for item in types_part.split(",")]
    values = [item.strip() for item in values_part.split(",")]
    entries: list[dict[str, Any]] = []
    for index, value in enumerate(values):
        if not value:
            continue
        entries.append(
            {
                "rank": index + 2,
                "type": types[index] if index < len(types) else "",
                "value": to_int(value, 0) if value.lstrip("-").isdigit() else value,
            }
        )
    return entries


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return to_int(str(value))


def _stars(value: Any) -> int | None:
    """PRTS stores rarity 0-based (0 = 1★); expose the familiar 1-6 scale."""
    rarity = _int_or_none(value)
    return None if rarity is None else rarity + 1


def _coalesce(*values: Any, default: Any = None) -> Any:
    """First value that is neither ``None`` nor an empty string (keeps ``0``)."""
    for value in values:
        if value is not None and value != "":
            return value
    return default


class Crawler:
    def __init__(self, config: CrawlConfig) -> None:
        settings = load_settings()
        config.workers = settings.workers if config.workers is None else config.workers
        config.rate = settings.rate if config.rate is None else config.rate
        config.timeout = settings.timeout if config.timeout is None else config.timeout
        config.retries = settings.retries if config.retries is None else config.retries
        config.with_media = settings.with_media if config.with_media is None else config.with_media

        self.config = config
        self.index_source = "unknown"
        self.client = HttpClient(
            headers=settings.headers,
            rate=config.rate,
            retries=config.retries,
            timeout=config.timeout,
            verbose=config.verbose,
        )
        self.cargo = CargoSource(self.client)
        self.html_index = HtmlIndexSource(self.client)
        self.wikitext = WikitextSource(self.client)
        self.media = MediaDownloader(self.client, config.out_dir / "media")

    # ------------------------------------------------------------------ paths
    @property
    def index_path(self) -> Path:
        return self.config.out_dir / "index.json"

    @property
    def wikitext_cache(self) -> Path:
        return self.config.out_dir / "cache" / "wikitext"

    @property
    def dataset_path(self) -> Path:
        return self.config.out_dir / "operators.json"

    @property
    def dataset_jsonl(self) -> Path:
        return self.config.out_dir / "operators.jsonl"

    @property
    def meta_path(self) -> Path:
        return self.config.out_dir / "meta.json"

    def _log(self, message: str) -> None:
        print(message, flush=True)

    # ------------------------------------------------------------------ index
    def load_index(self) -> list[dict[str, Any]]:
        if self.index_path.exists() and not self.config.refresh:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
            rows = payload.get("rows", payload) if isinstance(payload, dict) else payload
            self.index_source = payload.get("source", "cache") if isinstance(payload, dict) else "cache"
            self._log(f"[index] cache hit: {len(rows)} 条")
            return rows

        self._log("[index] cargoquery ...")
        try:
            rows = self.cargo.fetch_index()
            source = "cargoquery"
        except CargoError as exc:
            self._log(f"[index] cargo failed ({exc}); falling back to rendered HTML")
            rows = self.html_index.fetch_index()
            source = "parse:text"
        self.index_source = source

        if not rows:
            raise RuntimeError("index is empty; the wiki layout may have changed")

        if self.config.limit:
            rows = rows[: self.config.limit]

        _write_json(
            self.index_path,
            {"source": source, "fetchedAt": _now(), "count": len(rows), "rows": rows},
        )
        self._log(f"[index] {len(rows)} 条 (source={source})")
        return rows

    # ---------------------------------------------------------------- details
    def _cache_file(self, page: str) -> Path:
        return self.wikitext_cache / f"{safe_filename(page)}.wiki"

    def load_details(self, pages: Sequence[str]) -> dict[str, str]:
        texts: dict[str, str] = {}
        missing: list[str] = []

        if not self.config.refresh:
            for page in pages:
                cached = self._cache_file(page)
                if cached.exists():
                    texts[page] = cached.read_text(encoding="utf-8")
                else:
                    missing.append(page)
            if missing:
                self._log(f"[detail] cache hit {len(texts)}, fetch {len(missing)}")
        else:
            missing = list(pages)

        if missing:
            self.wikitext_cache.mkdir(parents=True, exist_ok=True)
            fetched = self.wikitext.fetch_many(missing, workers=self.config.workers)
            for page, text in fetched.items():
                texts[page] = text
                self._cache_file(page).write_text(text, encoding="utf-8")
            unresolved = [page for page in missing if page not in fetched]
            if unresolved:
                self._log(f"[detail] {len(unresolved)} page(s) missing: {unresolved[:5]}")
        return texts

    # ------------------------------------------------------------------ merge
    def build_records(
        self,
        index_rows: Sequence[dict[str, Any]],
        page_texts: dict[str, str],
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        clean = strip_html
        for row in index_rows:
            page = row.get("page") or row.get("name") or ""
            detail = parse_operator_page(page, page_texts.get(page, "")) if page else {}
            if detail.get("redirect"):
                target = detail["redirect"]
                detail = parse_operator_page(target, page_texts.get(target, ""))
            info = detail.get("info") or {}
            obtain = detail.get("obtain") or {}
            stats = detail.get("stats") or {}
            profile = detail.get("profile") or {}

            methods = obtain.get("methods") or [
                clean(item) for item in split_list(row.get("obtain", ""))
            ]
            trust = split_list(row.get("trust", "")) or []

            records.append(
                {
                    "charId": _coalesce(row.get("charId"), info.get("charId")),
                    "charIndex": _coalesce(
                        _int_or_none(row.get("charIndex")), info.get("charIndex")
                    ),
                    "name": _coalesce(row.get("page"), info.get("name")),
                    "nameJp": _coalesce(row.get("jp"), info.get("nameJp"), default=""),
                    "nameEn": _coalesce(row.get("en"), info.get("nameEn"), default=""),
                    "rarity": _coalesce(_stars(row.get("rarity")), _stars(info.get("rarity"))),
                    "profession": _coalesce(row.get("profession"), info.get("profession")),
                    "subProfession": _coalesce(
                        row.get("subProfession"), info.get("subProfession")
                    ),
                    "position": _coalesce(row.get("position"), info.get("position")),
                    "tags": split_list(clean(row.get("tag", ""))) or info.get("tags", []),
                    "nation": clean(_coalesce(row.get("nation"), info.get("nation"), default="")),
                    "org": clean(_coalesce(row.get("org"), info.get("org"), default="")),
                    "team": clean(_coalesce(row.get("team"), info.get("team"), default="")),
                    "logo": clean(row.get("logo", "")),
                    "eid": _coalesce(row.get("eid"), info.get("eid")),
                    "sex": _coalesce(clean(row.get("sex", "")), profile.get("sex")),
                    "race": _coalesce(clean(row.get("race", "")), profile.get("race")),
                    "birthPlace": _coalesce(
                        clean(row.get("birthPlace", "")), profile.get("birthPlace")
                    ),
                    "obtain": {
                        "methods": methods,
                        "coverage": clean(obtain.get("coverage", "")),
                        "releaseTime": obtain.get("releaseTime", ""),
                    },
                    "attributes": {
                        "hp": _int_or_none(row.get("hp")),
                        "atk": _int_or_none(row.get("atk")),
                        "def": _int_or_none(row.get("def")),
                        "res": _int_or_none(row.get("res")),
                        "cost": _coalesce(stats.get("cost"), _int_or_none(row.get("cost"))),
                        "block": _coalesce(stats.get("block"), _int_or_none(row.get("block"))),
                        "redeploy": _coalesce(stats.get("redeploy"), row.get("reDeploy"), default=""),
                        "attackInterval": _coalesce(
                            stats.get("attackInterval"), row.get("atkSpeed"), default=""
                        ),
                        "feature": _coalesce(info.get("feature"), clean(row.get("feature", "")), default=""),
                        "factions": {
                            "ingame": split_list(clean(row.get("ingameFaction", ""))),
                            "hidden": split_list(clean(row.get("hiddenFaction", ""))),
                        },
                        "grades": {
                            "physicalStrength": _coalesce(
                                clean(row.get("phy", "")), profile.get("physicalStrength")
                            ),
                            "mobility": _coalesce(
                                clean(row.get("flex", "")), profile.get("mobility")
                            ),
                            "endurance": _coalesce(
                                clean(row.get("tolerance", "")), profile.get("endurance")
                            ),
                            "tactics": _coalesce(
                                clean(row.get("plan", "")), profile.get("tactics")
                            ),
                            "combatSkill": _coalesce(
                                clean(row.get("skillRating", "")), profile.get("combatSkill")
                            ),
                            "artsAdaptability": _coalesce(
                                clean(row.get("adapt", "")), profile.get("artsAdaptability")
                            ),
                        },
                        "trustBonus": stats.get("trustBonus")
                        or {
                            "hp": _int_or_none(trust[0]) if len(trust) > 0 else 0,
                            "atk": _int_or_none(trust[1]) if len(trust) > 1 else 0,
                            "def": _int_or_none(trust[2]) if len(trust) > 2 else 0,
                        },
                    },
                    "potential": detail.get("potential")
                    or _split_potential(row.get("potential", "")),
                    "phases": detail.get("phases", []),
                    "talents": detail.get("talents", []),
                    "skills": detail.get("skills", []),
                    "modules": detail.get("modules", []),
                    "buildingSkills": detail.get("buildingSkills", []),
                    "profile": profile,
                    "description": detail.get("description", {}),
                    "voiceActors": info.get("voiceActors", {}),
                    "painter": info.get("painter", ""),
                    "avatar": {"file": f"头像_{row.get('page') or info.get('name')}.png"},
                    "source": {
                        "page": f"{WIKI_BASE}/w/{row.get('page') or info.get('name')}",
                        "api": API_URL,
                        "indexPage": INDEX_PAGE,
                    },
                }
            )
        return records

    # ------------------------------------------------------------------ media
    def attach_media(self, records: Sequence[dict[str, Any]]) -> int:
        names = [record["name"] for record in records if record.get("name")]
        if not names:
            return 0

        avatars = avatar_titles(names)
        professions = [record.get("profession", "") for record in records]
        icons = profession_icon_titles(professions)

        self._log(f"[media] resolving {len(avatars)} avatars + {len(icons)} profession icons")
        resolved = self.media.resolve(list(avatars) + list(icons))

        avatar_dir = self.config.out_dir / "media" / "avatars"
        icon_dir = self.config.out_dir / "media" / "professions"
        downloaded = 0

        for record in records:
            name = record.get("name")
            if not name:
                continue
            info = resolved.get(f"File:头像_{name}.png")
            if not info:
                continue
            destination = avatar_dir / f"{safe_filename(name)}.png"
            try:
                if self.media.download(info["url"], destination, info.get("size")):
                    downloaded += 1
            except Exception as exc:  # pragma: no cover - network flake
                self._log(f"[media] avatar failed for {name}: {exc}")
                continue
            record["avatar"] = {
                "file": urllib.parse.unquote(info.get("url", "").rsplit("/", 1)[-1]),
                "url": info["url"],
                "path": destination.relative_to(self.config.out_dir).as_posix(),
                "width": info.get("width"),
                "height": info.get("height"),
            }

        for profession in {record.get("profession") for record in records}:
            if not profession:
                continue
            info = resolved.get(f"File:图标_职业_{profession}.png")
            if not info:
                continue
            destination = icon_dir / f"{safe_filename(profession)}.png"
            try:
                if self.media.download(info["url"], destination, info.get("size")):
                    downloaded += 1
            except Exception as exc:  # pragma: no cover
                self._log(f"[media] icon failed for {profession}: {exc}")

        self._log(f"[media] {downloaded} file(s) downloaded into {self.config.out_dir / 'media'}")
        return downloaded

    # -------------------------------------------------------------------- run
    def run(self, steps: Sequence[str] = ("index", "details", "media")) -> dict[str, Any]:
        started = time.time()
        index_rows = self.load_index()

        if "details" not in steps:
            # Index-only run: never touch the full dataset written by `details`.
            self._log(
                f"[index] 已写入 {self.index_path}（{len(index_rows)} 条），"
                "未生成 operators.json；如需完整数据请运行 details 或 all"
            )
            return {"count": len(index_rows), "withDetails": False, "coverage": {}}

        pages = [row.get("page", "") for row in index_rows if row.get("page")]
        self._log(f"[detail] fetching wikitext for {len(pages)} pages")
        texts = self.load_details(pages)
        records = self.build_records(index_rows, texts)
        if not self.config.keep_wikitext:
            for page in pages:
                cache = self._cache_file(page)
                if cache.exists():
                    cache.unlink()
            try:
                self.wikitext_cache.rmdir()
                self.wikitext_cache.parent.rmdir()
            except OSError:
                pass

        if "media" in steps and self.config.with_media:
            self.attach_media(records)

        records.sort(key=lambda record: (record.get("charIndex") or 10**6, record.get("name") or ""))
        _write_jsonl(self.dataset_jsonl, records)

        meta = {
            "source": f"{WIKI_BASE}/w/{INDEX_PAGE}",
            "indexSource": self.index_source,
            "fetchedAt": _now(),
            "count": len(records),
            "withDetails": "details" in steps,
            "withMedia": self.config.with_media and "media" in steps,
            "requests": self.client.request_count,
            "elapsedSeconds": round(time.time() - started, 1),
            "coverage": {
                "skills": sum(1 for record in records if record["skills"]),
                "talents": sum(1 for record in records if record["talents"]),
                "modules": sum(1 for record in records if record["modules"]),
                "buildingSkills": sum(1 for record in records if record["buildingSkills"]),
                "phases": sum(1 for record in records if record["phases"]),
            },
        }
        _write_json(
            self.dataset_path,
            {"meta": meta, "operators": records},
        )
        _write_json(self.meta_path, meta)
        self._log(
            f"[done] {len(records)} operators, {self.client.request_count} HTTP requests, "
            f"{meta['elapsedSeconds']}s -> {self.dataset_path}"
        )
        return meta
