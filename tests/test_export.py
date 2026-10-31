from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from prts_crawler.export import (
    export,
    load_dataset,
    render_html,
    render_markdown,
    resolve_formats,
)

OPERATORS = [
    {
        "charId": "char_103_angel",
        "charIndex": 103,
        "name": "能天使",
        "nameEn": "Exusiai",
        "nameJp": "エクシア",
        "rarity": 6,
        "profession": "狙击",
        "subProfession": "速射手",
        "position": "远程位",
        "tags": ["输出", "削弱"],
        "attributes": {
            "hp": 1673,
            "atk": 540,
            "def": 161,
            "res": 0,
            "cost": 12,
            "block": 1,
        },
        "skills": [
            {
                "name": "冲锋模式",
                "recovery": "攻击回复",
                "activation": "自动触发",
                "levels": {"7": {"spCost": 4, "description": "7 级效果"}},
                "mastery": {"m3": {"description": "专三效果 | 带竖线"}},
            }
        ],
        "talents": [
            {"name": "快速弹匣", "condition": "精英1", "description": "攻击速度+6"}
        ],
        "modules": [
            {
                "name": "能天使的杰作",
                "type": "MAR-X",
                "stages": {"atk": [27, 35, 41], "hp": [110, 160, 190]},
            }
        ],
        "buildingSkills": [
            {"name": "企鹅物流·α", "room": "贸易站", "phase": "精英0", "description": "效率+20%"}
        ],
    },
    {
        "charId": "char_002_amiya",
        "charIndex": 2,
        "name": "阿米娅<测试>",
        "rarity": 5,
        "profession": "术师",
        "subProfession": "中坚术师",
        "position": "远程位",
        "tags": [],
        "attributes": {"hp": 1480, "atk": 612, "def": 100, "res": 20, "cost": 19, "block": 1},
        "skills": [],
        "talents": [],
        "modules": [],
        "buildingSkills": [],
    },
]


class FormatResolutionTests(unittest.TestCase):
    def test_known_values(self) -> None:
        self.assertEqual(resolve_formats("md"), ["md"])
        self.assertEqual(resolve_formats("markdown"), ["md"])
        self.assertEqual(resolve_formats("HTML"), ["html"])
        self.assertEqual(resolve_formats("both"), ["md", "html"])
        self.assertEqual(resolve_formats(""), [])
        self.assertEqual(resolve_formats("none"), [])
        self.assertEqual(resolve_formats("off"), [])

    def test_unknown_value_raises(self) -> None:
        with self.assertRaises(ValueError):
            resolve_formats("pdf")


class MarkdownTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.md = render_markdown(OPERATORS, {"fetchedAt": "2026-10-31T12:00:00+08:00"})

    def test_header_and_overview_table(self) -> None:
        self.assertIn("# PRTS 干员一览", self.md)
        self.assertIn("共 **2** 名干员", self.md)
        self.assertIn("| # | 名称 | 星级 | 职业 |", self.md)
        self.assertIn("| 103 | 能天使 | ★★★★★★ | 狙击 | 速射手 |", self.md)

    def test_grouped_by_profession(self) -> None:
        self.assertIn("### 狙击（1）", self.md)
        self.assertIn("### 术师（1）", self.md)
        self.assertIn("**能天使** ★★★★★★ · 速射手 · 技能：冲锋模式 · 天赋：快速弹匣", self.md)

    def test_pipe_in_value_is_escaped(self) -> None:
        # 技能描述里的竖线既不进表格也不该破坏行结构
        self.assertNotIn("专三效果 | 带竖线", self.md)

    def test_missing_fields_do_not_break_output(self) -> None:
        self.assertIn("阿米娅<测试>", self.md)


class HtmlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.page = render_html(OPERATORS, {"fetchedAt": "2026-10-31T12:00:00+08:00"})

    def test_self_contained(self) -> None:
        self.assertTrue(self.page.startswith("<!doctype html>"))
        self.assertIn("<style>", self.page)
        self.assertIn("<script>", self.page)
        self.assertNotIn("http://", self.page)
        self.assertNotIn("https://", self.page)

    def test_avatar_paths_are_relative(self) -> None:
        self.assertIn('src="../media/avatars/能天使.png"', self.page)
        self.assertIn('loading="lazy"', self.page)

    def test_search_index_and_counter(self) -> None:
        self.assertIn('data-search="能天使 exusiai エクシア 狙击 速射手 远程位 输出 削弱"', self.page)
        self.assertIn('id="cnt"', self.page)

    def test_sections_render_and_escape(self) -> None:
        self.assertIn("技能 1 个", self.page)
        self.assertIn("天赋 1 条", self.page)
        self.assertIn("模组 1 个", self.page)
        self.assertIn("基建技能 1 个", self.page)
        self.assertIn("阿米娅&lt;测试&gt;", self.page)

    def test_expanded_card_spans_grid(self) -> None:
        self.assertIn(".card:has(details[open]){grid-column:1/-1}", self.page)


class ExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.out = Path(self._tmp.name)

    def test_writes_requested_formats_only(self) -> None:
        written = export(OPERATORS, self.out, ["md"])
        self.assertEqual([p.name for p in written], ["operators.md"])
        self.assertTrue((self.out / "exports" / "operators.md").exists())
        self.assertFalse((self.out / "exports" / "operators.html").exists())

    def test_both_formats(self) -> None:
        written = export(OPERATORS, self.out, ["md", "html"], {"count": 2})
        self.assertEqual(sorted(p.name for p in written), ["operators.html", "operators.md"])

    def test_no_formats_writes_nothing(self) -> None:
        self.assertEqual(export(OPERATORS, self.out, []), [])
        self.assertFalse((self.out / "exports").exists())

    def test_load_dataset_round_trip(self) -> None:
        path = self.out / "operators.json"
        path.write_text(
            json.dumps({"meta": {"count": 2}, "operators": OPERATORS}, ensure_ascii=False),
            encoding="utf-8",
        )
        operators, meta = load_dataset(path)
        self.assertEqual(len(operators), 2)
        self.assertEqual(meta["count"], 2)

    def test_load_dataset_accepts_bare_list(self) -> None:
        path = self.out / "bare.json"
        path.write_text(json.dumps(OPERATORS, ensure_ascii=False), encoding="utf-8")
        operators, meta = load_dataset(path)
        self.assertEqual(len(operators), 2)
        self.assertEqual(meta, {})


if __name__ == "__main__":
    unittest.main()
