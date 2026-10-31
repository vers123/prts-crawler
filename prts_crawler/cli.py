"""Command line interface: ``prts-crawler ...`` or ``python -m prts_crawler ...``.

All defaults come from the ``.env`` file (or the real environment), so nothing
has to be exported by hand. ``--env-file`` loads a different file instead.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import Settings, load_settings
from .env import ENV_FILE_VAR, find_dotenv, load_dotenv
from .export import FORMAT_CHOICES, resolve_formats
from .pipeline import CrawlConfig, Crawler

STEPS = ("index", "details", "media", "export")


def _preload_env_file(argv: list[str]) -> Path | None:
    """Apply ``--env-file`` before the parser is built, so help shows real defaults."""
    for index, token in enumerate(argv):
        if token == "--env-file" and index + 1 < len(argv):
            return load_dotenv(argv[index + 1], override=True)
        if token.startswith("--env-file="):
            return load_dotenv(token.split("=", 1)[1], override=True)
    return load_dotenv()


def build_parser(settings: Settings, env_path: Path | None = None) -> argparse.ArgumentParser:
    env_hint = f"当前: {env_path}" if env_path else f"未找到 .env（可用 {ENV_FILE_VAR} 指定）"
    parser = argparse.ArgumentParser(
        prog="prts-crawler",
        description="抓取 https://prts.wiki/w/干员一览 的干员数据",
        epilog=f"配置来自 .env —— {env_hint}",
    )
    parser.add_argument(
        "step",
        nargs="?",
        default="all",
        choices=(*STEPS, "all"),
        help="index=仅列表, details=列表+详情, media=额外下载图片, "
        "export=从已有数据重新导出视图, all=全部",
    )
    parser.add_argument(
        "--env-file",
        metavar="PATH",
        default=None,
        help="改用指定的 .env 文件（默认自动查找项目根目录）",
    )
    parser.add_argument(
        "-o",
        "--out",
        default=str(settings.out_dir),
        help=f"输出目录 (默认: {settings.out_dir})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=settings.limit,
        help=f"只抓取前 N 名干员 (默认: {settings.limit or '全部'})",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=settings.workers,
        help=f"并发批次数 (默认: {settings.workers})",
    )
    parser.add_argument(
        "--rps",
        type=float,
        default=settings.rate,
        help=f"每秒请求数上限 (默认: {settings.rate:g})",
    )
    parser.add_argument("--refresh", action="store_true", help="忽略本地缓存重新抓取")
    parser.add_argument(
        "--format",
        dest="formats",
        default=settings.export_format,
        choices=FORMAT_CHOICES,
        help=f"导出人类可读视图的格式 (默认: {settings.export_format})",
    )
    media = parser.add_mutually_exclusive_group()
    media.add_argument(
        "--media",
        dest="media",
        action="store_true",
        default=settings.with_media,
        help="下载图片（.env 中 PRTS_MEDIA=1 时默认开启）",
    )
    media.add_argument(
        "--no-media",
        dest="media",
        action="store_false",
        help="跳过图片下载",
    )
    parser.add_argument("--keep-wikitext", action="store_true", help="保留原始 wikitext 缓存")
    parser.add_argument("-v", "--verbose", action="store_true", help="输出调试信息")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    env_path = _preload_env_file(argv)
    settings = load_settings()

    args = build_parser(settings, env_path).parse_args(argv)

    if args.step == "all":
        steps = list(STEPS)
    elif args.step == "index":
        steps = ["index"]
    elif args.step == "details":
        steps = ["index", "details"]
    elif args.step == "media":
        steps = ["index", "details", "media"]
    else:
        steps = ["export"]

    if args.verbose:
        print(f"[env] {env_path or '未加载 .env'}", flush=True)
        print(
            f"[env] rate={args.rps:g}/s workers={args.workers} "
            f"timeout={settings.timeout:g}s retries={settings.retries} "
            f"media={args.media} limit={args.limit or '全部'} format={args.formats}",
            flush=True,
        )
        print(f"[env] ua={settings.user_agent}", flush=True)

    config = CrawlConfig(
        out_dir=Path(args.out).resolve(),
        workers=max(1, args.workers),
        rate=max(0.1, args.rps),
        timeout=settings.timeout,
        retries=settings.retries,
        limit=args.limit,
        refresh=args.refresh,
        with_media=args.media,
        keep_wikitext=args.keep_wikitext,
        verbose=args.verbose,
        export_formats=tuple(resolve_formats(args.formats)),
    )

    crawler = Crawler(config)
    try:
        meta = crawler.run_export() if steps == ["export"] else crawler.run(steps)
    except KeyboardInterrupt:
        print("\n已取消", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - surface a clean message
        print(f"抓取失败: {exc}", file=sys.stderr)
        return 1

    coverage = meta.get("coverage") or {}
    if meta.get("exports"):
        print(f"已导出: {', '.join(meta['exports'])}")
    if coverage:
        print(
            f"完成: {meta['count']} 名干员 | 技能 {coverage.get('skills', 0)} | "
            f"天赋 {coverage.get('talents', 0)} | 模组 {coverage.get('modules', 0)}"
        )
    elif meta.get("count"):
        print(f"完成: 索引 {meta['count']} 条（未抓取详情）")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())