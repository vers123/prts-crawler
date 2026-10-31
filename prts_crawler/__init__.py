"""PRTS (明日方舟中文 Wiki) 干员数据爬虫."""

from __future__ import annotations

__version__ = "0.1.0"

from .cargo import CargoSource  # noqa: E402
from .detail import WikitextSource, parse_operator_page  # noqa: E402
from .http import HttpClient, HttpError  # noqa: E402
from .pipeline import CrawlConfig, Crawler  # noqa: E402

__all__ = [
    "CargoSource",
    "CrawlConfig",
    "Crawler",
    "HttpClient",
    "HttpError",
    "WikitextSource",
    "parse_operator_page",
    "__version__",
]
