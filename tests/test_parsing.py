from __future__ import annotations

import unittest

from prts_crawler.detail import parse_operator_page
from prts_crawler.pipeline import _split_potential
from prts_crawler.wikitext import (
    find_templates,
    parse_template,
    split_list,
    strip_markup,
)

SAMPLE = """{{干员页面名|能天使|能天使|Exusiai}}
==干员信息==
{{CharinfoV2
|干员名=能天使
|干员名jp=エクシア
|干员外文名=Exusiai
|干员id=char_103_angel
|干员序号=103
|特性=优先攻击{{color|#00B0FF|空中}}单位
|稀有度=6
|职业=狙击
|分支=速射手
|情报编号=PL01
|所属国家=拉特兰
|所属组织=
|所属团队=企鹅物流
|位置=远程位
|标签=输出 削弱
|画师=infukun
|中文配音=陶典
}}
==获得方式==
{{干员获得方式
|获得方式=公开招募 主线剧情
|上线时间=2019-05-01 10:00
}}
==属性==
{{属性
|再部署=70s
|部署费用=14
|阻挡数=1
|攻击速度=1s
|精英0_1级_生命上限=711
|精英0_1级_攻击=178
|精英0_1级_防御=57
|精英0_1级_法术抗性=0
|精英0_满级=50
|精英0_满级_生命上限=1015
|精英0_满级_攻击=254
|精英0_满级_防御=81
|精英0_满级_法术抗性=0
|精英2_满级=90
|精英2_满级_生命上限=1673
|精英2_满级_攻击=630
|精英2_满级_防御=134
|精英2_满级_法术抗性=0
|信赖加成_生命上限=0
|信赖加成_攻击=90
|信赖加成_防御=0
|潜能=-1,27,6,31,3
|潜能类型=cost,atk,def,atk,re_deploy
}}
==天赋==
{{天赋列表3
|天赋=第一天赋
|天赋1=快速弹匣
|天赋1条件=精英1
|天赋1效果=攻击速度+6
}}
==技能==
{{技能
|技能名=冲锋模式
|技能类型1=攻击回复
|技能类型2=自动触发
|技能1描述=下次攻击变为{{color|#0098DC|3}}连射
|技能1初始=0
|技能1消耗=5
|技能1持续=
|技能专精3描述=下次攻击变为{{color|#0098DC|5}}连射
|技能专精3初始=0
|技能专精3消耗=4
|技能专精3持续=
}}
==后勤技能==
{{后勤技能
|后勤技能1-1=企鹅物流·α
|后勤技能1-1ID=bskill_meet_spd2
|后勤技能1-1房间=贸易站
|后勤技能1-1描述=进驻贸易站时，订单获取效率{{color|#0098DC|+20%}}
|后勤技能1-1阶段=精英0
}}
==干员档案==
{{人员档案set
|性别=女
|战斗经验=三年
|出身地=拉特兰
|生日=12月24日
|种族=萨科塔
|身高=159cm
|物理强度=标准
|战场机动=优良
}}
==模组==
{{模组
|名称=能天使证章
|模组图标=uniequip_001_angel
|类型图标=original
|基础证章=yes
|分支=速射手
|基础信息=能天使擅长远程狙击<br>特别颁发此证章
}}
{{模组
|名称=能天使的杰作
|模组图标=uniequip_002_angel
|类型图标=mar-x
|类型=MAR-X
|生命=110
|攻击=27
|生命2=160
|攻击2=35
|生命3=190
|攻击3=41
|解锁等级=60
|特性追加=yes
|特性=攻击空中目标时攻击力提升
|天赋2=天赋【快速弹匣】更新
}}
"""


class WikitextTests(unittest.TestCase):
    def test_parse_template_splits_params_and_nested_values(self) -> None:
        template = parse_template("{{属性|再部署=70s|潜能类型=cost,atk|精英0_满级=50}}")
        self.assertEqual(template.name, "属性")
        self.assertEqual(template.params["再部署"], "70s")
        self.assertEqual(template.params["潜能类型"], "cost,atk")

    def test_strip_markup_flattens_colour_and_links(self) -> None:
        self.assertEqual(
            strip_markup("优先攻击{{color|#00B0FF|空中}}单位"),
            "优先攻击空中单位",
        )
        self.assertEqual(strip_markup("见[[干员一览|列表]]"), "见列表")
        self.assertEqual(strip_markup("a<br/>b"), "a\nb")

    def test_strip_markup_keeps_label_of_terminology_templates(self) -> None:
        self.assertEqual(strip_markup("结束后{{术语|ba.stun|晕眩}}10秒"), "结束后晕眩10秒")
        self.assertEqual(strip_markup("恢复{{变动数值lite|up|蓝|3}}点技力"), "恢复3点技力")
        self.assertEqual(
            strip_markup("（[[TR-10_范围杀伤|{{color|orange|TR-10}}]]）"),
            "（TR-10）",
        )

    def test_find_templates_is_case_sensitive_and_deduplicated(self) -> None:
        found = find_templates(SAMPLE, "技能")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].get("技能名"), "冲锋模式")

    def test_strip_markup_keeps_angle_bracket_mechanics(self) -> None:
        # PRTS 用尖括号表示游戏内机制名，不能被当成 HTML 标签删掉
        self.assertEqual(strip_markup("<震撼装置>消耗费用"), "<震撼装置>消耗费用")
        self.assertEqual(strip_markup("不受<部署数量>限制"), "不受<部署数量>限制")
        self.assertEqual(
            strip_markup('<span style="color:#00B0FF;">空中</span>单位'),
            "空中单位",
        )
        self.assertEqual(strip_markup("<b>粗体</b>与<references/>"), "粗体与")

    def test_split_list_handles_cjk_separators(self) -> None:
        self.assertEqual(split_list("输出 削弱"), ["输出", "削弱"])
        self.assertEqual(split_list("公开招募，主线剧情"), ["公开招募", "主线剧情"])


class DetailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.record = parse_operator_page("能天使", SAMPLE)

    def test_info_block(self) -> None:
        info = self.record["info"]
        self.assertEqual(info["charId"], "char_103_angel")
        self.assertEqual(info["rarity"], 6)
        self.assertEqual(info["profession"], "狙击")
        self.assertEqual(info["tags"], ["输出", "削弱"])
        self.assertEqual(info["voiceActors"]["zh"], "陶典")

    def test_phases_only_include_present_elites(self) -> None:
        phases = self.record["phases"]
        self.assertEqual([phase["elite"] for phase in phases], [0, 2])
        self.assertEqual(phases[1]["max"]["atk"], 630)

    def test_skill_levels_and_mastery(self) -> None:
        skill = self.record["skills"][0]
        self.assertEqual(skill["name"], "冲锋模式")
        self.assertEqual(skill["levels"]["1"]["spCost"], 5)
        self.assertEqual(skill["mastery"]["m3"]["description"], "下次攻击变为5连射")

    def test_talents_and_building_skills(self) -> None:
        self.assertEqual(self.record["talents"][0]["name"], "快速弹匣")
        building = self.record["buildingSkills"][0]
        self.assertEqual(building["room"], "贸易站")
        self.assertEqual(building["description"], "进驻贸易站时，订单获取效率+20%")

    def test_obtain_and_profile(self) -> None:
        self.assertEqual(self.record["obtain"]["methods"], ["公开招募", "主线剧情"])
        self.assertEqual(self.record["profile"]["race"], "萨科塔")

    def test_modules_keep_all_three_stages(self) -> None:
        modules = self.record["modules"]
        self.assertEqual(len(modules), 2)
        badge, upgraded = modules
        self.assertTrue(badge["baseBadge"])
        self.assertEqual(badge["type"], "original")
        self.assertEqual(badge["stages"]["hp"], [])
        self.assertEqual(upgraded["name"], "能天使的杰作")
        self.assertEqual(upgraded["type"], "MAR-X")
        self.assertEqual(upgraded["unlockLevel"], 60)
        self.assertEqual(upgraded["stages"]["hp"], [110, 160, 190])
        self.assertEqual(upgraded["stages"]["atk"], [27, 35, 41])
        self.assertEqual(upgraded["talentUpgrades"]["stage2"], "天赋【快速弹匣】更新")

    def test_potential_string_parsing(self) -> None:
        entries = _split_potential("cost,atk,def,atk,re_deploy`-1,27,6,31,3")
        self.assertEqual(entries[0], {"rank": 2, "type": "cost", "value": -1})
        self.assertEqual(entries[4]["type"], "re_deploy")


if __name__ == "__main__":
    unittest.main()
