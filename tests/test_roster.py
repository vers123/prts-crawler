from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from prts_crawler.roster import (
    Entry,
    infer_elite,
    infer_elite_by_cap,
    load_entries,
    match_operator,
    max_elite,
    normalize_name,
    phase_caps,
    render_markdown,
    resolve_entries,
    summarize,
)

OPERATORS = [
    {
        "charId": "char_172_svrash",
        "name": "银灰",
        "nameEn": "SilverAsh",
        "nameJp": "シルバーアッシュ",
        "rarity": 6,
        "profession": "近卫",
        "phases": [
            {"elite": 0, "maxLevel": 50},
            {"elite": 1, "maxLevel": 80},
            {"elite": 2, "maxLevel": 90},
        ],
    },
    {
        "charId": "char_123_fang",
        "name": "芬",
        "nameEn": "Fang",
        "nameJp": "フェン",
        "rarity": 3,
        "profession": "先锋",
        "phases": [{"elite": 0, "maxLevel": 40}, {"elite": 1, "maxLevel": 55}],
    },
    {
        "charId": "char_291_aglina",
        "name": "凯尔希·思衡托",
        "nameEn": "Kal'tsit",
        "nameJp": "ケルシー",
        "rarity": 6,
        "profession": "医疗",
        "phases": [
            {"elite": 0, "maxLevel": 50},
            {"elite": 1, "maxLevel": 80},
            {"elite": 2, "maxLevel": 90},
        ],
    },
]


class NormalizeTests(unittest.TestCase):
    def test_spaces_and_separators_folded(self) -> None:
        self.assertEqual(normalize_name("凯尔希 思衡托"), normalize_name("凯尔希·思衡托"))
        self.assertEqual(normalize_name("ＡＢ"), normalize_name("ＡＢ").casefold())


class MatchTests(unittest.TestCase):
    def test_exact_name(self) -> None:
        operator, method, score = match_operator("银灰", OPERATORS)
        assert operator is not None
        self.assertEqual(operator["charId"], "char_172_svrash")
        self.assertEqual(method, "名称精确匹配")
        self.assertEqual(score, 100)

    def test_foreign_and_japanese_names(self) -> None:
        operator, method, _ = match_operator("SilverAsh", OPERATORS)
        assert operator is not None
        self.assertEqual(operator["name"], "银灰")
        self.assertEqual(method, "外文名精确匹配")

        operator, method, _ = match_operator("フェン", OPERATORS)
        assert operator is not None
        self.assertEqual(operator["name"], "芬")
        self.assertEqual(method, "日文名精确匹配")

    def test_normalised_name(self) -> None:
        operator, method, _ = match_operator("凯尔希 思衡托", OPERATORS)
        assert operator is not None
        self.assertEqual(operator["name"], "凯尔希·思衡托")
        self.assertIn(method, {"名称归一化匹配", "名称包含匹配"})

    def test_no_match(self) -> None:
        operator, method, score = match_operator("查无此干员", OPERATORS)
        self.assertIsNone(operator)
        self.assertEqual((method, score), ("", 0))

    def test_blank_name(self) -> None:
        self.assertEqual(match_operator("   ", OPERATORS), (None, "", 0))


class PhaseTests(unittest.TestCase):
    def test_caps_and_max_elite(self) -> None:
        operator = OPERATORS[0]
        self.assertEqual(phase_caps(operator), {0: 50, 1: 80, 2: 90})
        self.assertEqual(max_elite(operator), 2)
        self.assertEqual(max_elite({"phases": []}), 0)

    def test_infer_elite_definite(self) -> None:
        self.assertEqual(infer_elite(OPERATORS[0], 90), (2, [2]))
        self.assertEqual(infer_elite(OPERATORS[1], 55), (1, [1]))

    def test_infer_elite_ambiguous(self) -> None:
        elite, candidates = infer_elite(OPERATORS[0], 80)
        self.assertIsNone(elite)
        self.assertEqual(candidates, [1, 2])

    def test_infer_elite_impossible(self) -> None:
        elite, candidates = infer_elite(OPERATORS[1], 99)
        self.assertIsNone(elite)
        self.assertEqual(candidates, [])

    def test_cap_match_uses_exact_cap(self) -> None:
        # 80 恰为 E1 上限 → 推定为 E1
        self.assertEqual(infer_elite_by_cap(OPERATORS[0], 80), (1, [1, 2]))
        # 50 恰为 E0 上限
        self.assertEqual(infer_elite_by_cap(OPERATORS[0], 50), (0, [0, 1, 2]))
        # 3★ Lv40 恰为 E0 上限
        self.assertEqual(infer_elite_by_cap(OPERATORS[1], 40), (0, [0, 1]))

    def test_cap_match_falls_back_to_single_candidate(self) -> None:
        self.assertEqual(infer_elite_by_cap(OPERATORS[0], 90), (2, [2]))

    def test_cap_match_stays_unknown_without_exact_cap(self) -> None:
        elite, candidates = infer_elite_by_cap(OPERATORS[0], 77)
        self.assertIsNone(elite)
        self.assertEqual(candidates, [1, 2])


class ResolveTests(unittest.TestCase):
    def test_definite_inference_is_recorded(self) -> None:
        resolutions = resolve_entries([Entry("银灰", level=90)], OPERATORS)
        self.assertEqual(resolutions[0].entry.elite, 2)
        self.assertEqual(resolutions[0].issues, [])
        self.assertTrue(
            any("精英化由等级推定" in note for note in resolutions[0].notes)
        )

    def test_ambiguous_inference_uses_exact_cap(self) -> None:
        # Lv80 恰为精英1上限 → 按上限推定，并记录依据
        resolutions = resolve_entries([Entry("银灰", level=80)], OPERATORS)
        self.assertEqual(resolutions[0].entry.elite, 1)
        self.assertEqual(resolutions[0].issues, [])
        self.assertTrue(any("按上限推定" in note for note in resolutions[0].notes))

    def test_ambiguous_without_cap_match_stays_unknown(self) -> None:
        # Lv77 不等于任何档位上限 → 不猜，标记待确认
        resolutions = resolve_entries([Entry("银灰", level=77)], OPERATORS)
        self.assertIsNone(resolutions[0].entry.elite)
        self.assertTrue(any("精英化需确认" in issue for issue in resolutions[0].issues))

    def test_level_above_elite_cap_is_flagged(self) -> None:
        resolutions = resolve_entries([Entry("银灰", level=90, elite=1)], OPERATORS)
        self.assertTrue(any("超出 精英1 上限 Lv80" in issue for issue in resolutions[0].issues))

    def test_elite_above_operator_max_is_flagged(self) -> None:
        resolutions = resolve_entries([Entry("芬", level=10, elite=2)], OPERATORS)
        self.assertTrue(any("超出该干员上限 精英1" in issue for issue in resolutions[0].issues))

    def test_duplicates_are_noted(self) -> None:
        resolutions = resolve_entries(
            [
                Entry("银灰", level=90, elite=2, screenshot="a.jpg"),
                Entry("银灰", level=90, elite=2, screenshot="b.jpg"),
            ],
            OPERATORS,
        )
        self.assertEqual(len(resolutions), 2)
        self.assertEqual(resolutions[1].issues, [])
        self.assertTrue(any("重复" in note for note in resolutions[1].notes))
        self.assertEqual(summarize(resolutions)["duplicates"], 1)

    def test_unmatched_and_low_confidence(self) -> None:
        resolutions = resolve_entries(
            [Entry("查无此人", level=1), Entry("芬", level=30, elite=0, confidence="low")],
            OPERATORS,
        )
        self.assertEqual(resolutions[0].operator, None)
        self.assertIn("未匹配到 PRTS 干员", resolutions[0].issues)
        self.assertTrue(any("置信度 low" in issue for issue in resolutions[1].issues))

    def test_summary_counts(self) -> None:
        resolutions = resolve_entries(
            [
                Entry("银灰", level=90, elite=2),
                Entry("芬", level=30, elite=0),
                Entry("查无此人", level=1),
            ],
            OPERATORS,
        )
        summary = summarize(resolutions)
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["matched"], 2)
        self.assertEqual(summary["unique"], 2)
        self.assertEqual(summary["unmatched"], ["查无此人"])


class RenderTests(unittest.TestCase):
    def test_table_has_level_and_elite_columns(self) -> None:
        resolutions = resolve_entries(
            [Entry("银灰", level=90, elite=2), Entry("芬", level=55, elite=1)], OPERATORS
        )
        markdown = render_markdown(resolutions, {"capturedAt": "2026-11-01"})
        self.assertIn("| PRTS 头像 | 干员 | 星级 | 职业 | 等级 | 精英化 |", markdown)
        self.assertIn("| 银灰 | ★★★★★★ | 近卫 | Lv90 | 精英2 |", markdown)
        self.assertIn("| 芬 | ★★★ | 先锋 | Lv55 | 精英1 |", markdown)
        self.assertIn("截图日期 2026-11-01", markdown)

    def test_dedupes_and_sorts_by_rarity(self) -> None:
        resolutions = resolve_entries(
            [
                Entry("芬", level=55, elite=1),
                Entry("银灰", level=90, elite=2, screenshot="a.jpg"),
                Entry("银灰", level=90, elite=2, screenshot="b.jpg"),
            ],
            OPERATORS,
        )
        markdown = render_markdown(resolutions)
        self.assertEqual(markdown.count("| 银灰 |"), 1)
        self.assertLess(markdown.index("银灰"), markdown.index("芬"))

    def test_unmatched_entries_are_omitted(self) -> None:
        resolutions = resolve_entries([Entry("查无此人", level=1)], OPERATORS)
        markdown = render_markdown(resolutions)
        self.assertNotIn("查无此人", markdown)
        self.assertIn("共 0 名", markdown)


class LoadEntriesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_accepts_objects_and_plain_strings(self) -> None:
        path = self.dir / "entries.json"
        path.write_text(
            json.dumps(
                {
                    "meta": {"capturedAt": "2026-11-01"},
                    "entries": [
                        {"name": "银灰", "level": 90, "elite": 2, "screenshot": "a.jpg"},
                        "芬",
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        entries, meta = load_entries(path)
        self.assertEqual(meta["capturedAt"], "2026-11-01")
        self.assertEqual(entries[0].level, 90)
        self.assertEqual(entries[1].name, "芬")
        self.assertIsNone(entries[1].level)

    def test_bare_list(self) -> None:
        path = self.dir / "bare.json"
        path.write_text(json.dumps(["银灰", "芬"], ensure_ascii=False), encoding="utf-8")
        entries, meta = load_entries(path)
        self.assertEqual([entry.name for entry in entries], ["银灰", "芬"])
        self.assertEqual(meta, {})


if __name__ == "__main__":
    unittest.main()
