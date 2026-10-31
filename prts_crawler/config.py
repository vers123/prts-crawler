"""Configuration: built-in defaults, overridable by ``.env`` or real env vars.

Tunables are read through :func:`load_settings` (never captured at import time),
so ``--env-file`` and late environment changes are honoured.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .env import env_bool, env_float, env_int, env_str

WIKI_BASE = "https://prts.wiki"
API_URL = f"{WIKI_BASE}/api.php"
MEDIA_BASE = "https://media.prts.wiki"

#: The page rendered by Template:干员筛选.
INDEX_PAGE = "干员一览"

BUILTIN_USER_AGENT = (
    "prts-crawler/0.1 (personal data collection; contact: set PRTS_USER_AGENT)"
)

#: PRTS sits behind a Tengine CDN that replies ``403 Forbidden`` to any request
#: without an ``Accept-Language`` header (verified: UA-only and UA+Referer are
#: both rejected, UA+Accept-Language passes). Keep it in every request.
BASE_HEADERS = {
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
}

BUILTIN_RATE = 4.0
BUILTIN_WORKERS = 4
BUILTIN_TIMEOUT = 30.0
BUILTIN_RETRIES = 5
BUILTIN_OUT_DIR = "data"

#: MediaWiki caps ``action=query`` titles at 50 per request for anonymous users.
MAX_TITLES_PER_BATCH = 50

#: ``action=cargoquery`` caps ``limit`` at 500 rows per request.
MAX_CARGO_LIMIT = 500


@dataclass(frozen=True)
class Settings:
    """Resolved runtime settings (env vars already merged with ``.env``)."""

    user_agent: str
    rate: float
    workers: int
    timeout: float
    retries: int
    out_dir: Path
    limit: int | None
    with_media: bool

    @property
    def headers(self) -> dict[str, str]:
        return {**BASE_HEADERS, "User-Agent": self.user_agent}


def load_settings() -> Settings:
    """Read tunables from the environment.

    Recognised variables (all optional)::

        PRTS_USER_AGENT  UA 字符串，建议带上联系方式
        PRTS_RATE        每秒请求数上限（默认 4）
        PRTS_WORKERS     并发批次数（默认 4）
        PRTS_TIMEOUT     单请求超时秒数（默认 30）
        PRTS_RETRIES     重试次数（默认 5）
        PRTS_OUT_DIR     输出目录（默认 data）
        PRTS_LIMIT       只抓前 N 名，0 或留空表示全部
        PRTS_MEDIA       是否下载图片，1/0
    """
    limit = env_int("PRTS_LIMIT", 0)
    return Settings(
        user_agent=env_str("PRTS_USER_AGENT", BUILTIN_USER_AGENT),
        rate=max(0.1, env_float("PRTS_RATE", BUILTIN_RATE)),
        workers=max(1, env_int("PRTS_WORKERS", BUILTIN_WORKERS)),
        timeout=max(1.0, env_float("PRTS_TIMEOUT", BUILTIN_TIMEOUT)),
        retries=max(0, env_int("PRTS_RETRIES", BUILTIN_RETRIES)),
        out_dir=Path(env_str("PRTS_OUT_DIR", BUILTIN_OUT_DIR)),
        limit=limit if limit > 0 else None,
        with_media=env_bool("PRTS_MEDIA", True),
    )