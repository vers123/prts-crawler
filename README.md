# PRTS 干员数据爬虫

抓取 [PRTS 干员一览](https://prts.wiki/w/干员一览) 的全量干员数据（434 名），
输出结构化 JSON / JSONL 与本地图片缓存。纯标准库实现，**无第三方依赖**。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

数据来源与逆向过程见 [docs/data-sources.md](docs/data-sources.md)。

## 快速开始

项目使用独立的 `.venv` 虚拟环境，**不向全局 Python 安装任何包**。
项目本身零第三方依赖，虚拟环境只装它自己和 `pip`。

```powershell
cd D:\LingLan\projects\hypergryph\arknights
$env:PYTHONUTF8 = '1'

# 首次：创建虚拟环境并把项目装进去（可编辑模式，仅作用于 .venv）
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .

# 之后每次使用前激活
.\.venv\Scripts\Activate.ps1
```

```powershell
prts-crawler all              # 列表 + 详情 + 图片 + 导出
prts-crawler index            # 只要列表（1 次请求）
prts-crawler details          # 列表 + 详情（不下载图片）
prts-crawler export           # 从已有数据重新渲染 md/html，不联网
prts-crawler all --limit 20   # 小样本试跑
prts-crawler all --refresh    # 忽略缓存重抓
```

不想激活也能直接用解释器调用：`.\.venv\Scripts\python.exe -m prts_crawler all`。

## 配置（.env）

所有可调参数都走 `.env`，不需要手动 `export` 环境变量。

```powershell
Copy-Item .env.example .env    # 已生成，改里面的联系方式即可
```

优先级：**命令行参数 > 真实环境变量 > `.env` > 内置默认值**。

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `PRTS_USER_AGENT` | `prts-crawler/0.1 (...)` | 请求 UA，**请填自己的联系方式** |
| `PRTS_RATE` | `4` | 每秒请求数上限，勿调高 |
| `PRTS_WORKERS` | `4` | 并发批次数 |
| `PRTS_TIMEOUT` | `30` | 单请求超时（秒） |
| `PRTS_RETRIES` | `5` | 失败重试次数 |
| `PRTS_OUT_DIR` | `data` | 输出目录 |
| `PRTS_LIMIT` | `0` | 只抓前 N 名，`0`/留空 = 全部 |
| `PRTS_MEDIA` | `1` | 是否下载图片，`1`/`0` |
| `PRTS_EXPORT_FORMAT` | `both` | 导出视图格式：`md` / `html` / `both` / `none` |

`.env` 自动发现顺序：当前目录向上最多 6 层 → 项目根目录。
也可以用 `PRTS_ENV_FILE` 环境变量或 `--env-file` 参数指定别的文件：

```powershell
prts-crawler --env-file .env.ci -v all
# [env] .env.ci
# [env] rate=1.5/s workers=2 timeout=30s retries=5 media=False limit=3
```

`.env` 已被 `.gitignore` 忽略，只提交 `.env.example`；个人 UA 不会泄露进仓库。

输出（默认 `data/`）：

```
data/
├── index.json          # Cargo 原始列表（434 行）
├── operators.json      # 合并后的数据集（含 meta）
├── operators.jsonl     # 逐行版本，便于流式处理
├── meta.json           # 统计：请求数、耗时、各字段覆盖率
├── exports/            # 人类可读视图
│   ├── operators.md    #   总览表 + 按职业分组（diff 友好，约 120 KB）
│   └── operators.html  #   单文件看板，带图 / 搜索 / 折叠（约 1.3 MB）
└── media/
    ├── avatars/        # 头像 434 张
    └── professions/    # 职业图标
```

## 两种视图怎么选

|\ | Markdown | HTML |
|---|---|---|
| 定位 | 进仓库做版本对比 | 浏览、交付、打印 PDF |
| 体积（434 名全量） | 120 KB | 1.3 MB（含全部技能/天赋/模组表） |
| 头像 | 无 | 434 张，`loading="lazy"` |
| 搜索筛选 | 无 | 输入「狙击」→ 命中 59 条 |
| 折叠长表 | 无 | 1670 个 `<details>` |
| Git diff | ✅ 一行一名干员 | ❌ 单文件不可读 |
| 外部依赖 | 无 | 无（CSS/JS 全内联，0 个外部 URL） |

Markdown 只放总览表与技能/天赋名称，逐级数值留在 HTML 里 —— 否则每张子表都要重复表头，
体积会涨到 1.9 MB 且完全没法 review。

```powershell
prts-crawler export --format html    # 只出看板
prts-crawler export --format md      # 只出摘要
prts-crawler export --format none    # 只要 JSON
```

`operators.html` 直接双击就能看，图片走相对路径 `../media/avatars/`，整个 `data/` 目录可打包带走。

## 数据示例

```json
{
  "charId": "char_103_angel",
  "charIndex": 103,
  "name": "能天使",
  "rarity": 6,
  "profession": "狙击",
  "subProfession": "速射手",
  "position": "远程位",
  "tags": ["输出", "削弱"],
  "nation": "拉特兰",
  "attributes": {
    "hp": 1673, "atk": 630, "def": 134, "res": 0,
    "cost": 14, "block": 1,
    "redeploy": "70s", "attackInterval": "1s",
    "feature": "优先攻击空中单位",
    "trustBonus": {"hp": 0, "atk": 90, "def": 0}
  },
  "potential": [{"rank": 2, "type": "cost", "value": -1, "description": "部署费用-1"}],
  "phases": [{"elite": 2, "maxLevel": 90, "level1": {...}, "max": {...}}],
  "talents": [{"slot": 1, "name": "快速弹匣", "condition": "精英1", "description": "..."}],
  "skills": [{"index": 1, "name": "冲锋模式", "recovery": "攻击回复", "levels": {...}, "mastery": {...}}],
  "modules": [{"name": "能天使的杰作", "type": "MAR-X", "stages": {...}}],
  "buildingSkills": [{"slot": 1, "name": "企鹅物流·α", "room": "贸易站", "description": "..."}],
  "profile": {"race": "萨科塔", "height": "159cm", "physicalStrength": "标准"},
  "avatar": {"path": "media/avatars/能天使.png", "url": "https://media.prts.wiki/..."}
}
```

## 架构

```
prts_crawler/
├── config.py     # 站点常量 + Settings（读取 env/.env）
├── env.py        # 零依赖 .env 解析器（引号/注释/优先级）
├── http.py       # 限速 + 重试 + gzip 的轻量客户端
├── cargo.py      # action=cargoquery 封装与索引查询
├── detail.py     # 批量 revisions + 页面模板解析
├── wikitext.py   # {{模板}} 解析器（支持嵌套 / 链接 / 着色清理）
├── fallback.py   # 兜底：解析 #filter-data 的 data-* 卡片
├── media.py      # imageinfo 解析 + 图片下载
├── export.py     # 渲染 Markdown 摘要 / HTML 看板（零依赖）
├── pipeline.py   # 编排：索引 → 详情 → 合并 → 媒体 → 导出
└── cli.py        # argparse 入口
```

## 抓取策略

| 数据 | 方式 | 请求数 |
| --- | --- | --- |
| 干员列表（面板/稀有度/职业/标签…） | `action=cargoquery` 一次取回 434 行 | 1 |
| 技能/天赋/模组/基建/档案 | `action=query&prop=revisions` 每批 50 页 | 9 |
| 头像 URL | `prop=imageinfo&iiprop=url` 每批 50 个 | 9 |
| 头像文件 | `media.prts.wiki` 直链 | 434 |

- **必须带 `Accept-Language`**：PRTS 的 Tengine CDN 对缺少该头的请求直接返回 403。
- 全局令牌桶限速（`PRTS_RATE`，默认 `4 req/s`）+ 429/5xx 指数退避；整轮约 460 请求、2 分钟。
- `data/cache/wikitext/` 缓存页面源码，`--refresh` 才会失效；解析规则调整后可离线重解析。
- 字段口径：`rarity` 已从源站的 0 基（0 = 1★）归一为 **1–6 星**；面板数值为满级、不含信赖。

## 字段说明

| 字段 | 含义 |
| --- | --- |
| `rarity` | 星级 1–6（源数据 0 基，已 +1） |
| `attributes.hp/atk/def/res` | 满级面板（不含信赖加成） |
| `attributes.trustBonus` | 信赖加成 |
| `potential` | 潜能 2–6，含 `type`（cost/atk/def/re_deploy…）与 `value` |
| `phases` | 精英化阶段，含 1 级与满级数值 |
| `talents` | 天赋各阶段（`slot` 为列表内序号） |
| `skills` | 技能含 `levels.1–7` 与 `mastery.m1–m3` |
| `modules` | 模组；`baseBadge: true` 表示基础证章 |
| `buildingSkills` | 基建技能（房间/阶段/描述） |

## 测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

覆盖模板解析、嵌套 `{{color}}`/链接清理、技能等级与专精、天赋、基建技能、潜能串解析，
`.env` 解析（引号/转义/注释/优先级）与配置归一化，以及导出（Markdown 转义、HTML 自包含、
格式选择、缺失字段容错）。

## 说明

- 数据版权归鹰角网络 / PRTS 社区所有，本项目仅做个人学习用途的数据聚合。
- 请遵守站点负载：不要调高 `PRTS_RATE`，不要并发跑多个实例。
- 建议在 `.env` 的 `PRTS_USER_AGENT` 里填自己的联系方式。

## 许可证

代码以 [MIT License](LICENSE) 发布，Copyright (c) 2026 vers123。
爬取到的数据与图片版权归原权利方所有，不在本许可证授权范围内。
