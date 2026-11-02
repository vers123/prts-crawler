from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from prts_crawler.lookup import (
    describe_stage,
    load_stages,
    natural_key,
    search_local,
)

STAGES = [
    {
        "key": "main_01-07",
        "stageId": "main_01-07",
        "code": "1-7",
        "name": "暴君",
        "page": "1-7 暴君",
        "type": "主线",
        "area": "第一章 黑暗时代·下",
        "recommendedLevel": "LV.10",
        "deployLimit": 8,
        "initialCost": 10,
        "costLimit": 99,
        "lifePoints": 10,
        "enemyCount": 41,
        "mapSize": "11×7",
        "fastestTime": "1分58秒",
        "sanity": 6,
        "drillSanity": 1,
        "storyOnly": False,
        "description": "配合使用<震撼装置>",
        "enemies": [{"name": "暴徒", "count": 4}, {"name": "士兵", "count": 7}],
        "devices": [{"name": "震撼装置", "level": 10, "skill": "EMP爆炸"}],
        "challenge": {
            "difficulty": "FOUR_STAR",
            "description": "附加条件：\n部署费用回复减半",
            "intel": "敌方单位属性提升至120%",
        },
    },
    {
        "key": "main_07-18",
        "stageId": "main_07-18",
        "code": "7-18",
        "name": "爱国者之死",
        "page": "7-18 爱国者之死",
        "type": "主线",
        "storyOnly": False,
        "description": "",
        "enemies": [],
        "devices": [],
        "challenge": None,
    },
    {
        "key": "st_08-02",
        "stageId": "st_08-02",
        "code": "M8-2",
        "name": "失语，产自多言",
        "page": "M8-2 失语，产自多言",
        "type": "主线",
        "storyOnly": True,
        "description": "剧情文本",
        "enemies": [],
        "devices": [],
        "challenge": None,
    },
]


class NaturalKeyTests(unittest.TestCase):
    def test_numbers_sort_numerically(self) -> None:
        codes = ["7-18", "7-2", "7-10", "10-1"]
        self.assertEqual(
            sorted(codes, key=natural_key), ["7-2", "7-10", "7-18", "10-1"]
        )

    def test_mixed_text_and_numbers(self) -> None:
        self.assertLess(natural_key("H7-1"), natural_key("H10-1"))


class SearchLocalTests(unittest.TestCase):
    def test_exact_stage_id(self) -> None:
        matches = search_local(STAGES, "main_01-07")
        self.assertEqual(matches[0].code, "1-7")
        self.assertEqual(matches[0].reason, "关卡 id 精确匹配")
        self.assertEqual(matches[0].score, 100)

    def test_exact_code(self) -> None:
        matches = search_local(STAGES, "1-7")
        self.assertEqual(matches[0].code, "1-7")
        self.assertEqual(matches[0].reason, "关卡代号精确匹配")

    def test_exact_name(self) -> None:
        matches = search_local(STAGES, "暴君")
        self.assertEqual(matches[0].code, "1-7")
        self.assertEqual(matches[0].reason, "关卡名精确匹配")

    def test_page_title(self) -> None:
        matches = search_local(STAGES, "7-18 爱国者之死")
        self.assertEqual(matches[0].code, "7-18")

    def test_code_plus_name_matches_page_title(self) -> None:
        # 真实数据里页面标题就是「代号 名称」，优先命中页面精确匹配
        matches = search_local(STAGES, "1-7 暴君")
        self.assertEqual(matches[0].code, "1-7")
        self.assertEqual(matches[0].reason, "页面标题精确匹配")

    def test_code_plus_name_when_page_differs(self) -> None:
        stage = dict(STAGES[0], page="暴君（旧标题）")
        matches = search_local([stage], "1-7 暴君")
        self.assertEqual(matches[0].reason, "代号 + 名称精确匹配")

    def test_partial_name_and_code_are_ranked_below_exact(self) -> None:
        matches = search_local(STAGES, "爱国者")
        self.assertEqual(matches[0].code, "7-18")
        self.assertEqual(matches[0].reason, "关卡名包含查询")

    def test_case_insensitive(self) -> None:
        self.assertEqual(search_local(STAGES, "m8-2")[0].code, "M8-2")

    def test_exact_beats_contains(self) -> None:
        extra = {
            "key": "x",
            "stageId": "main_01-07x",
            "code": "1-70",
            "name": "占位",
            "page": "1-70 占位",
            "enemies": [],
            "devices": [],
            "challenge": None,
        }
        matches = search_local([*STAGES, extra], "1-7")
        self.assertEqual(matches[0].code, "1-7")

    def test_no_match_and_blank_query(self) -> None:
        self.assertEqual(search_local(STAGES, "不存在"), [])
        self.assertEqual(search_local(STAGES, "   "), [])


class DescribeStageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = describe_stage(STAGES[0])

    def test_identity_and_constraints(self) -> None:
        self.assertIn("1-7 暴君", self.text)
        self.assertIn("id=main_01-07", self.text)
        self.assertIn("部署上限=8", self.text)
        self.assertIn("目标点耐久=10", self.text)

    def test_enemy_summary_counts(self) -> None:
        self.assertIn("敌人（2 种 / 共 11）", self.text)
        self.assertIn("暴徒×4", self.text)

    def test_device_and_challenge(self) -> None:
        self.assertIn("震撼装置(Lv10)", self.text)
        self.assertIn("突袭：FOUR_STAR", self.text)
        self.assertIn("敌方单位属性提升至120%", self.text)

    def test_missing_values_render_as_dash(self) -> None:
        text = describe_stage(STAGES[2])
        self.assertIn("部署上限=-", text)
        self.assertIn("剧情关=是", text)

    def test_device_without_level(self) -> None:
        stage = dict(STAGES[0], devices=[{"name": "源石流发生装置", "level": None}])
        self.assertIn("装置：源石流发生装置", describe_stage(stage))


class LoadStagesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_reads_dataset_payload(self) -> None:
        path = self.dir / "stages.json"
        path.write_text(
            json.dumps({"meta": {"count": 3}, "stages": STAGES}, ensure_ascii=False),
            encoding="utf-8",
        )
        self.assertEqual(len(load_stages(path)), 3)

    def test_reads_bare_list(self) -> None:
        path = self.dir / "bare.json"
        path.write_text(json.dumps(STAGES, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(len(load_stages(path)), 3)


if __name__ == "__main__":
    unittest.main()
