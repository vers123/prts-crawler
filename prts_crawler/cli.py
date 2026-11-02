"""Command line interface: ``prts-crawler ...`` or ``python -m prts_crawler ...``.

All defaults come from the ``.env`` file (or the real environment), so nothing
has to be exported by hand. ``--env-file`` loads a different file instead.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import Settings, load_settings
from .env import ENV_FILE_VAR, find_dotenv, load_dotenv
from .export import FORMAT_CHOICES, resolve_formats
from .http import HttpClient
from .lookup import (
    describe_stage,
    fetch_remote_stage,
    load_stages,
    remote_search,
    search_local,
)
from .pipeline import CrawlConfig, Crawler
from .roster import (
    backup_file,
    load_entries,
    load_operators,
    render_fill_sheet,
    render_markdown,
    resolve_entries,
    summarize,
)
from .stages import SCOPE_CHOICES

STEPS = (
    "index",
    "details",
    "media",
    "export",
    "stages",
    "enemies",
    "operators",
    "stage",
    "roster",
)

DEFAULT_ROSTER_OUT = "guide/data/operators/owned-operators.md"


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
        "export=从已有数据重新导出视图, stages=抓关卡+敌人, enemies=只补敌人, "
        "stage=查询单个关卡, roster=核对识别名单, operators=干员全流程, "
        "all=干员+关卡+敌人",
    )
    parser.add_argument(
        "query",
        nargs="?",
        default=None,
        help="配合 stage 使用：关卡代号(1-7)、名称(暴君) 或 id(main_01-07)",
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
        "--stage-scope",
        default="main",
        choices=SCOPE_CHOICES,
        help="关卡范围：main=主线, event=活动, all=全部普通难度关卡 (默认: main)",
    )
    parser.add_argument(
        "--all-enemies",
        action="store_true",
        help="抓取 分类:敌人 全部敌人，而不是只补齐关卡引用到的敌人",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="配合 stage 使用：输出原始 JSON 而不是摘要",
    )
    parser.add_argument(
        "--pick",
        action="store_true",
        help="配合 stage 使用：多个候选同分时直接取第一个",
    )
    parser.add_argument(
        "--entries",
        metavar="PATH",
        default=None,
        help="配合 roster 使用：识别结果 JSON 路径",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="配合 roster 使用：确认无误后写入持有名单（默认只预览）",
    )
    parser.add_argument(
        "--roster-out",
        metavar="PATH",
        default=DEFAULT_ROSTER_OUT,
        help=f"配合 roster 使用：名单输出路径 (默认: {DEFAULT_ROSTER_OUT})",
    )
    parser.add_argument(
        "--fill-sheet",
        action="store_true",
        help="配合 roster 使用：输出待人工核对的填写模板（等级已填，其余留空）",
    )
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


def _run_stage_lookup(args, settings) -> int:
    """``prts-crawler stage <query>``: local index first, then PRTS search."""
    if not args.query:
        print("用法: prts-crawler stage <代号|名称|id>", file=sys.stderr)
        return 2

    out_dir = Path(args.out).resolve()
    stages_path = out_dir / "stages.json"
    stages = load_stages(stages_path) if stages_path.exists() else []
    if not stages:
        print(
            f"[stage] 本地未找到 {stages_path}，转向 PRTS 搜索（可先运行 stages 建立索引）",
            file=sys.stderr,
        )

    matches = search_local(stages, args.query)
    if matches:
        top = matches[0]
        rivals = [m for m in matches[1:] if m.score == top.score]
        if rivals and not args.pick:
            print(f"「{args.query}」匹配到 {1 + len(rivals)} 个同等优先级的关卡：", file=sys.stderr)
            for match in [top, *rivals][:10]:
                print(f"  {match.code:<10} {match.name:<14} ({match.reason})", file=sys.stderr)
            print("请用更精确的代号或名称重试。", file=sys.stderr)
            return 3
        if args.json:
            print(json.dumps(top.stage, ensure_ascii=False, indent=2))
        else:
            print(describe_stage(top.stage))
            print(f"  命中依据：{top.reason}")
        return 0

    titles = remote_search(HttpClient(rate=args.rps), args.query)
    candidates = fetch_remote_stage(HttpClient(rate=args.rps), titles[:3])
    if not candidates:
        print(f"未找到关卡「{args.query}」；可用 prts-crawler stages 更新本地索引后重试。", file=sys.stderr)
        if titles:
            print("搜索到的页面（非关卡）：" + "、".join(titles), file=sys.stderr)
        return 4

    stage = candidates[0]
    if args.json:
        print(json.dumps(stage, ensure_ascii=False, indent=2))
    else:
        print(describe_stage(stage))
        print("  命中依据：PRTS 搜索（本地索引未收录）")
    return 0


def _run_roster(args) -> int:
    """``prts-crawler roster --entries <json> [--write]``."""
    if not args.entries:
        print("用法: prts-crawler roster --entries <识别结果.json> [--write]", file=sys.stderr)
        return 2

    entries_path = Path(args.entries).resolve()
    if not entries_path.exists():
        print(f"找不到识别结果: {entries_path}", file=sys.stderr)
        return 2

    operators_path = Path(args.out).resolve() / "operators.json"
    if not operators_path.exists():
        print(f"找不到 {operators_path}；请先运行 operators", file=sys.stderr)
        return 2

    entries, meta = load_entries(entries_path)
    operators = load_operators(operators_path)
    resolutions = resolve_entries(entries, operators)
    summary = summarize(resolutions)

    print(
        f"识别 {summary['total']} 张卡片 → 匹配 {summary['matched']}、"
        f"去重后 {summary['unique']} 名"
    )
    if summary["duplicates"]:
        print(f"滚动重叠重复 {summary['duplicates']} 张，已自动去重")
    if summary["inferredElite"]:
        print(f"精英化已由等级推定 {summary['inferredElite']} 名")
    if summary["pendingElite"]:
        names = summary["pendingElite"]
        preview = "、".join(names[:8]) + ("…" if len(names) > 8 else "")
        print(f"精英化待确认 {len(names)} 名：{preview}")
    if summary["unmatched"]:
        print("未匹配：" + "、".join(summary["unmatched"]))
    for detail in summary["issueDetails"]:
        if "精英化需确认" not in detail:
            print(f"  ! {detail}")

    markdown = (
        render_fill_sheet(resolutions, {**meta, "dataset": "data/operators.json"})
        if args.fill_sheet
        else render_markdown(resolutions, {**meta, "dataset": "data/operators.json"})
    )
    out_path = Path(args.roster_out)
    if not out_path.is_absolute():
        out_path = Path.cwd() / out_path

    if not args.write:
        kind = "填写模板" if args.fill_sheet else "名单"
        print(f"\n预览完成，尚未写入{kind}。确认无误后加 --write 写入 {out_path}")
        print(f"（将写入 {len(markdown.splitlines())} 行）")
        return 0 if summary["unmatched"] == [] else 3

    out_path.parent.mkdir(parents=True, exist_ok=True)
    backup = backup_file(out_path)
    if backup is not None:
        print(f"已备份原文件 → {backup}")
    out_path.write_text(markdown, encoding="utf-8", newline="\n")
    print(f"已写入 {out_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    env_path = _preload_env_file(argv)
    settings = load_settings()

    args = build_parser(settings, env_path).parse_args(argv)

    if args.step == "stage":
        try:
            return _run_stage_lookup(args, settings)
        except KeyboardInterrupt:
            return 130
        except Exception as exc:  # noqa: BLE001
            print(f"查询失败: {exc}", file=sys.stderr)
            return 1

    if args.step == "roster":
        try:
            return _run_roster(args)
        except KeyboardInterrupt:
            return 130
        except Exception as exc:  # noqa: BLE001
            print(f"名单核对失败: {exc}", file=sys.stderr)
            return 1

    STEP_MAP = {
        "all": ["index", "details", "media", "export", "stages", "enemies"],
        "operators": ["index", "details", "media", "export"],
        "index": ["index"],
        "details": ["index", "details"],
        "media": ["index", "details", "media"],
        "export": ["export"],
        "stages": ["stages", "enemies"],
        "enemies": ["enemies"],
    }
    steps = STEP_MAP[args.step]

    if args.verbose:
        print(f"[env] {env_path or '未加载 .env'}", flush=True)
        print(
            f"[env] rate={args.rps:g}/s workers={args.workers} "
            f"timeout={settings.timeout:g}s retries={settings.retries} "
            f"media={args.media} limit={args.limit or '全部'} format={args.formats} "
            f"stageScope={args.stage_scope}",
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
        stage_scope=args.stage_scope,
        all_enemies=args.all_enemies,
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
    if "stageCount" in meta:
        stage_meta = meta.get("stageMeta") or {}
        print(
            f"关卡: {meta['stageCount']} 个（范围 {stage_meta.get('scope')}）"
            f" | 含突袭 {stage_meta.get('withChallenge', 0)}"
            f" | 含敌人表 {stage_meta.get('withEnemies', 0)}"
        )
    if "enemyCount" in meta:
        enemy_meta = meta.get("enemyMeta") or {}
        print(
            f"敌人: {meta['enemyCount']} 个（{enemy_meta.get('scope')}）"
            f" | 未找到 {enemy_meta.get('unresolvedCount', 0)}"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())