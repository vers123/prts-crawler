from __future__ import annotations

import unittest

from prts_crawler.stages import (
    SCOPE_CATEGORIES,
    parse_enemy,
    parse_stage,
    referenced_enemies,
    resolve_scope,
    stage_key,
)

STAGE = """{{pathnav2|关卡一览}}
==剧情==
{{剧情跳转/关卡|1-7|暴君}}
==普通==
{{普通关卡信息
|关卡代号=1-7
|关卡名=暴君
|关卡id=main_01-07
|关卡类型=主线
|关卡难度=NORMAL
|解锁条件=2星通关[[TR-9 间接防护]]
|推荐等级=LV.10
|所属区域=第一章 黑暗时代·下
|部署上限=8
|初始COST=10
|COST上限=99
|目标点耐久=10
|敌人数量=41
|地图大小=11×7
|最短用时=1分58秒
|关卡描述=配合使用震撼装置。<br/>{{color|#FFFFFF|<震撼装置>}}可以开启
|作战消耗=6
|演习消耗=1
|首次掉落=梓兰:固定掉落,至纯源石:三星获得
|常规掉落=固源岩:固定掉落
|额外物资=源岩,代糖
}}
==突袭==
{{突袭关卡信息
|关卡代号=1-7
|关卡名=暴君
|关卡类型=主线
|关卡难度=FOUR_STAR
|作战消耗=6
|演习消耗=3
|关卡描述={{color|#FF0000|附加条件：}}<br>部署费用的自然回复速度减半
|情报=敌方单位的生命值、攻击力、防御力都提升至120%
}}
==敌方情报==
{{敌方情报
|敌人1=暴徒
|敌人1数量=4
|敌人1级别=0
|敌人2=源石虫·α
|敌人2数量=23
|敌人2级别=0
}}
==地图装置==
{{关卡装置
|装置名称=震撼装置
|装置等级=10
|装置技能=EMP爆炸
}}
"""

STORY_STAGE = """{{普通关卡信息
|关卡代号=M8-2
|关卡名=失语，产自多言
|关卡id=st_08-02
|关卡类型=主线
|战斗关卡=false
|作战消耗=18
|演习消耗=1
}}
"""

NOT_A_STAGE = "{{其他模板|foo=bar}}"

ENEMY = """{{敌人信息/common2
|id=53
|名称=暴徒
|index=17
|地位级别=普通
|描述=来路不明的作战人员。
|伤害类型=物理
|攻击方式=近战
|行动方式=地面
|登场活动=初始
}}
==级别0==
{{敌人信息/levelcontent
|index=0
|名称=暴徒
|地位=普通
|数量=1
|最大生命值=1700
|攻击力=250
|防御力=50
|法术抗性=0
|移动速度=1.1
|重量等级=0
|攻击范围半径=1.5
|眩晕抗性=无
|沉默抗性=有
}}
"""


class StageParseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.stage = parse_stage("1-7 暴君", STAGE)

    def test_basic_fields(self) -> None:
        stage = self.stage
        self.assertEqual(stage["stageId"], "main_01-07")
        self.assertEqual(stage["code"], "1-7")
        self.assertEqual(stage["name"], "暴君")
        self.assertEqual(stage["type"], "主线")
        self.assertEqual(stage["area"], "第一章 黑暗时代·下")
        self.assertEqual(stage["recommendedLevel"], "LV.10")
        self.assertEqual(stage["deployLimit"], 8)
        self.assertEqual(stage["initialCost"], 10)
        self.assertEqual(stage["lifePoints"], 10)
        self.assertEqual(stage["enemyCount"], 41)
        self.assertEqual(stage["mapSize"], "11×7")
        self.assertEqual(stage["sanity"], 6)

    def test_markup_is_flattened(self) -> None:
        self.assertIn("<震撼装置>", self.stage["description"])
        self.assertNotIn("color", self.stage["description"])
        self.assertEqual(self.stage["unlock"], "2星通关TR-9 间接防护")

    def test_drops_split_into_name_and_type(self) -> None:
        drops = self.stage["drops"]
        self.assertEqual(drops["first"][0], {"name": "梓兰", "type": "固定掉落"})
        self.assertEqual(drops["normal"], [{"name": "固源岩", "type": "固定掉落"}])
        self.assertEqual(drops["extra"], ["源岩", "代糖"])

    def test_enemy_groups(self) -> None:
        enemies = self.stage["enemies"]
        self.assertEqual(len(enemies), 2)
        self.assertEqual(enemies[0], {"name": "暴徒", "count": 4, "level": 0})
        self.assertEqual(enemies[1]["name"], "源石虫·α")
        self.assertEqual(enemies[1]["count"], 23)

    def test_devices(self) -> None:
        self.assertEqual(
            self.stage["devices"],
            [{"name": "震撼装置", "level": 10, "skill": "EMP爆炸"}],
        )

    def test_challenge_variant(self) -> None:
        challenge = self.stage["challenge"]
        self.assertIsNotNone(challenge)
        assert challenge is not None
        self.assertEqual(challenge["difficulty"], "FOUR_STAR")
        self.assertIn("部署费用的自然回复速度减半", challenge["description"])
        self.assertEqual(challenge["intel"], "敌方单位的生命值、攻击力、防御力都提升至120%")

    def test_combat_stage_is_not_story_only(self) -> None:
        # 1-7 未写 战斗关卡，默认视为战斗关
        self.assertTrue(self.stage["isBattle"])
        self.assertFalse(self.stage["storyOnly"])

    def test_story_stage_uses_battle_flag(self) -> None:
        stage = parse_stage("M8-2 失语，产自多言", STORY_STAGE)
        assert stage is not None
        self.assertFalse(stage["isBattle"])
        self.assertTrue(stage["storyOnly"])
        self.assertEqual(stage["sanity"], 18)

    def test_non_stage_page_returns_none(self) -> None:
        self.assertIsNone(parse_stage("别的页面", NOT_A_STAGE))

    def test_stage_key_prefers_stage_id(self) -> None:
        self.assertEqual(stage_key(self.stage), "main_01-07")
        self.assertEqual(stage_key({"code": "EX-1", "page": "EX-1 某关"}), "EX-1")
        self.assertEqual(stage_key({"page": "只 有页面"}), "只 有页面")


class EnemyParseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.enemy = parse_enemy("暴徒", ENEMY)

    def test_common_fields(self) -> None:
        assert self.enemy is not None
        self.assertEqual(self.enemy["name"], "暴徒")
        self.assertEqual(self.enemy["internalId"], 53)
        self.assertEqual(self.enemy["index"], 17)
        self.assertEqual(self.enemy["rank"], "普通")
        self.assertEqual(self.enemy["damageType"], "物理")
        self.assertEqual(self.enemy["attackMode"], "近战")
        self.assertEqual(self.enemy["moveMode"], "地面")

    def test_level_stats(self) -> None:
        assert self.enemy is not None
        level = self.enemy["levels"][0]
        self.assertEqual(level["level"], 0)
        self.assertEqual(level["hp"], 1700)
        self.assertEqual(level["atk"], 250)
        self.assertEqual(level["def"], 50)
        self.assertEqual(level["res"], 0)
        self.assertEqual(level["weight"], 0)
        self.assertEqual(level["attackRange"], "1.5")

    def test_resistances(self) -> None:
        assert self.enemy is not None
        resist = self.enemy["levels"][0]["resistances"]
        self.assertEqual(resist["stun"], "无")
        self.assertEqual(resist["silence"], "有")

    def test_missing_levels_returns_none(self) -> None:
        self.assertIsNone(parse_enemy("空页", "{{别的模板}}"))


class ScopeTests(unittest.TestCase):
    def test_resolve_scope(self) -> None:
        self.assertEqual(resolve_scope("main"), ["主线关卡"])
        self.assertEqual(resolve_scope("event"), ["活动关卡"])
        self.assertEqual(resolve_scope("all"), ["普通难度关卡"])
        self.assertEqual(resolve_scope(""), ["主线关卡"])
        self.assertEqual(set(SCOPE_CATEGORIES), {"main", "event", "all"})

    def test_unknown_scope_raises(self) -> None:
        with self.assertRaises(ValueError):
            resolve_scope("side")


class ReferencedEnemyTests(unittest.TestCase):
    def test_dedupes_in_first_seen_order(self) -> None:
        stages = [
            {"enemies": [{"name": "暴徒"}, {"name": "士兵"}]},
            {"enemies": [{"name": "士兵"}, {"name": "源石虫·α"}]},
            {"enemies": []},
        ]
        self.assertEqual(referenced_enemies(stages), ["暴徒", "士兵", "源石虫·α"])

    def test_skips_blank_names(self) -> None:
        self.assertEqual(referenced_enemies([{"enemies": [{"name": ""}]}]), [])


if __name__ == "__main__":
    unittest.main()
