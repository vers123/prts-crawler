# PRTS 干员一览：数据来源逆向分析

目标页面：<https://prts.wiki/w/干员一览>

分析方式：用浏览器打开页面，在 DevTools 的 Network / Elements 面板中定位数据请求，
再用 `curl` 逐条验证请求契约。

## 1. 页面不是静态表格

首屏 HTML 里 **没有任何 `<table>`**（`document.querySelectorAll('table').length === 0`），
列表由 Vue 组件渲染：

- 站点：MediaWiki 1.43.9 + Semantic MediaWiki + Cargo
- 皮肤：`skin-arknights`
- 列表组件：`Widget:CharList`（挂在页面最后的 `{{#widget:CharList}}`）

页面源码只有：

```wikitext
{{页面迭代}}{{Ads/normal}}{{Ads/mobile}}
{{干员筛选}}
{{#seo:...}}
```

## 2. 数据真正来自 Cargo，而不是 XHR

`Template:干员筛选` 里有一个隐藏的 `#cargo_query`：

```wikitext
<div style="display:none" id="filter-data">{{#cargo_query:
tables=chara,chara_data,chara_extra_info,char_obtain
|join on=chara._pageName=chara_data._pageName,chara._pageName=chara_extra_info._pageName,chara._pageName=char_obtain._pageName
|where=chara.charIndex>0
|fields=chara._pageName=干员,chara.profession=职业,...
|limit=5000
|format=template
|template=干员筛选数据/4
|more results text=
}}</div>{{#widget:CharList}}
```

也就是说：**434 条干员数据在一次页面解析时就被完整写进 HTML**，
前端只做筛选与分页（`共434条`，每页 50 条）。

### 结论 A：抓 HTML 也能拿到全量

`#filter-data` 内是 434 个带 `data-*` 属性的 `<div>`，长度约 364 KB：

```html
<div data-zh="12F" data-profession="术师" data-rarity="1" data-hp="1461"
     data-atk="432" data-def="50" data-res="10" data-cost="24" data-block="1"
     data-interval="2.9s" data-tag="新手" data-obtain-method="公开招募, 主线剧情"
     data-potential="cost,atk,re_deploy,atk,cost`-1,12,-5,12,-1"
     data-char-id="char_009_12fce" ...>...</div>
```

注意 `data-potential` 用反引号分隔「类型串」与「数值串」。

### 结论 B（本项目采用）：直接调用 Cargo API，拿干净 JSON

Cargo 把同一个查询暴露成 API：

```
GET https://prts.wiki/api.php?action=cargoquery&format=json
    &tables=chara,chara_data,chara_extra_info,char_obtain
    &join_on=chara._pageName=chara_data._pageName,...
    &fields=chara._pageName=page,chara.charId,chara.rarity,...
    &where=chara.charIndex>0&limit=500
```

实测：**一次请求返回全量（观测时 434 行、约 204 KB、耗时 421 ms；当前 440 条）**，无需分页、无 HTML 噪音。

## 3. 踩到的坑（已内建到代码里）

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `403 Forbidden`（Tengine） | CDN 要求 `Accept-Language` 头；只带 UA 或 UA+Referer 都会被拒 | `config.DEFAULT_HEADERS` 固定 `Accept-Language: zh-CN,zh;q=0.9` |
| `Special:CargoTables` 被 302 到 `sisyphus.prts.wiki` 人机校验 | 特殊页有反爬 | 不依赖特殊页；表名/字段从模板源码里读 |
| `chara_skill` / `chara_talent` 报 `MWException` | 这些表不存在 | 技能/天赋没有独立 Cargo 表，需解析模板源码 |
| 图片 `File:头像_X.png` 直接拼 URL 会 404 | 路径带 `a/ad/` 这类哈希前缀 | 用 `action=query&prop=imageinfo&iiprop=url` 批量解析 |
| `action=help&format=json` 返回 HTML | 该 wiki 未开放此模块 | 直接按 MediaWiki 约定试请求 |

## 4. 详情数据：解析模板源码

干员详情页没有商品化的 JSON 接口，正文本身就是结构化模板：
`{{CharinfoV2|...}}`、`{{属性|...}}`、`{{天赋列表3|...}}`、`{{技能|...}}`、
`{{模组|...}}`、`{{后勤技能|...}}`、`{{人员档案set|...}}`。

因此走 **批量读取源码** 而不是逐页抓 HTML：

```
GET /api.php?action=query&prop=revisions&rvslots=main&rvprop=content
    &format=json&formatversion=2&redirects=1&titles=A|B|C...   # 最多 50 个/次
```

440 个干员 = **9 次请求**，再由 `prts_crawler/wikitext.py` 的模板解析器拆分。

## 5. 关卡与敌人：同样是结构化模板

关卡一览页本身由 Semantic MediaWiki 的 `#ask` 拼接，没有可直接调用的 Cargo 表
（`stage` / `enemy` 等表名均不存在）。但**关卡页和敌人页的正文都是模板**，
因此沿用同一套批量 `revisions` 读取，只换解析目标。

关卡页（`1-7 暴君`）实测：

```wikitext
{{普通关卡信息
|关卡代号=1-7|关卡id=main_01-07|关卡类型=主线|关卡难度=NORMAL
|解锁条件=2星通关[[TR-9 间接防护]]|推荐等级=LV.10|所属区域=第一章 黑暗时代·下
|部署上限=8|初始COST=10|COST上限=99|目标点耐久=10|敌人数量=41|地图大小=11×7
|关卡描述=...<震撼装置>消耗一定部署费用可以开启...
|作战消耗=6|演习消耗=1|首次掉落=梓兰:固定掉落|常规掉落=固源岩:固定掉落}}
{{突袭关卡信息|...}}          <!-- 同页的突袭变体 -->
{{敌方情报|敌人1=暴徒|敌人1数量=4|敌人1级别=0|...}}
{{关卡装置|装置名称=震撼装置|装置等级=10|装置技能=EMP爆炸}}
```

敌人页（`暴徒`）：

```wikitext
{{敌人信息/common2|id=53|名称=暴徒|地位级别=普通|伤害类型=物理|攻击方式=近战|行动方式=地面}}
{{敌人信息/levelcontent|index=0|最大生命值=1700|攻击力=250|防御力=50|法术抗性=0
|移动速度=1.1|重量等级=0|眩晕抗性=无|沉默抗性=无|...}}
```

关卡枚举走分类查询：

```
GET /api.php?action=query&list=categorymembers&cmlimit=500&cmnamespace=0
    &cmtitle=分类:主线关卡          # 或 分类:活动关卡 / 分类:普通难度关卡
```

| 分类 | 页数 |
| --- | ---: |
| 主线关卡 | 487 |
| 活动关卡 | 2410 |
| 普通难度关卡 | 3670 |
| 敌人 | 1863 |

两个解析上的坑：

- **剧情关**没有敌人表和部署上限，但可能有作战消耗（如 `M8-2`，`战斗关卡=false`）。
  必须用 `战斗关卡` 标记区分，否则会和解析失败一样得到空值。
- **尖括号是机制名不是标签**：`<震撼装置>`、`<替身>` 若被当 HTML 标签删掉，
  数据会静默缺失。解析器改为只剥离白名单内的真实标签。

## 6. Cargo 表与字段（用于扩展）

| 表 | 写入模板 | 说明 |
| --- | --- | --- |
| `chara` | `Template:CharinfoV2` | 基础信息、职业、分支、标签、画师、时装名 |
| `chara_data` | `Template:属性` | 满级面板、再部署、费用、阻挡、潜能、信赖 |
| `chara_extra_info` | 页面属性（SMW 同步） | 出身地、种族、性别、六维评价 |
| `char_obtain` | `Template:干员获得方式` | 获得方式、上线时间 |
| `char_mod` | `Template:模组` | 模组名称、类型、三阶段数值 |
| `char_building_skill` | `Template:后勤技能` | 基建技能、房间、阶段 |

## 7. 请求预算与礼貌性

| 步骤 | 请求数 |
| --- | --- |
| 列表（Cargo） | 1 |
| 详情（批量 revisions） | ⌈440 / 50⌉ = 9 |
| 头像 imageinfo | ⌈440 / 50⌉ = 9 |
| 头像下载 | 440 |
| 职业图标 | ≈ 9 |
| 关卡分类枚举 | 1–6 |
| 关卡正文（主线 487 页） | ⌈487 / 50⌉ = 10 |
| 关卡引用敌人（321 个） | ⌈321 / 50⌉ = 7 |
| 合计 | ≈ 480 |

实现默认 `4 req/s` 全局限速 + 指数退避重试，干员全流程约 2 分钟，关卡链路约 10 秒。
