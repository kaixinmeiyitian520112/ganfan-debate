# test_agent_config.py
"""
Agent 配置测试 (3.6.7)
验证大厨与裁判的名称、立场、人设、菜单约束与分类识别
"""

import csv
import sys
import time
import unittest
from unittest.mock import AsyncMock, patch

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from backend.main import (
    DebateRequest,
    DebateSession,
    Speech,
    DebateReport,
    _fallback_speech,
    _fallback_report,
    _call_chef,
    _call_judge,
    _debate_stream,
    _menu_candidates,
)


class AgentConfigReport:
    def __init__(self):
        self.records = []

    def log(self, cid, name, passed, message="", cost_ms=0.0):
        self.records.append({
            "id": cid,
            "name": name,
            "passed": passed,
            "message": message,
            "cost_ms": round(cost_ms, 2)
        })

    def print_summary(self):
        total = len(self.records)
        passed = sum(1 for r in self.records if r["passed"])
        failed = total - passed
        print("\n" + "=" * 90)
        print("          Agent 人设与配置测试执行报告 (3.6.7)")
        print("=" * 90)
        print(f"{'编号':<6}{'测试内容':<40}{'耗时(ms)':<10}{'状态'}")
        print("-" * 90)
        for r in self.records:
            status = " [PASS] " if r["passed"] else "![FAIL]!"
            print(f"{r['id']:<6}{r['name']:<40}{r['cost_ms']:<10}{status}")
            if not r["passed"] and r["message"]:
                print(f"       -> 错误原因: {r['message']}")
        print("=" * 90)
        print(f"总计: {total} 个用例 | 通过: {passed} | 失败: {failed} | 成功率: {passed/max(1, total)*100:.1f}%\n")
        return failed == 0


REPORT = AgentConfigReport()


class TestAgentConfig(unittest.IsolatedAsyncioTestCase):
    def test_cfg01_default_fallback(self):
        """测试 1: 人设和立场留空时使用默认名称、立场和人设"""
        t0 = time.perf_counter()
        req = DebateRequest(
            taste="辣",
            budget=30,
            weather="晴",
            spicy_stance="  ",
            healthy_stance="  ",
            spicy_persona="  ",
            healthy_persona="  "
        )
        cost = (time.perf_counter() - t0) * 1000
        ok = (
            req.spicy_name == "辣子哥" and
            req.healthy_name == "清补凉" and
            req.spicy_stance == "spicy" and
            req.healthy_stance == "healthy" and
            "火爆川菜大厨" in req.spicy_persona and
            "温和粤菜师傅" in req.healthy_persona
        )
        REPORT.log("CFG01", "留空字段自动降级回退默认配置", ok, "", cost)
        self.assertTrue(ok)

    async def test_cfg02_custom_names_in_debate_and_report(self):
        """测试 2: 自定义大厨名称在发言历史与最终战报中正确呈现"""
        t0 = time.perf_counter()
        req = DebateRequest(
            taste="甜",
            budget=40,
            weather="晴",
            rounds=1,
            spicy_name="甜品大师",
            healthy_name="养生顾问"
        )
        session = DebateSession(id="test_custom_names", request=req)

        # 验证兜底发言使用新名称
        sp1 = _fallback_speech(session, "甜品大师", "甜味主张", None)
        sp2 = _fallback_speech(session, "养生顾问", "低糖主张", None)
        session.history.extend([sp1, sp2])

        # 验证兜底战报使用新名称
        report = _fallback_report(session)
        cost = (time.perf_counter() - t0) * 1000

        ok = (
            sp1.chef == "甜品大师" and
            sp2.chef == "养生顾问" and
            report.winner in {"甜品大师", "养生顾问"} and
            "甜品大师" in report.score and
            "养生顾问" in report.score
        )
        REPORT.log("CFG02", "自定义大厨名称全流程穿透与应用", ok, "", cost)
        self.assertTrue(ok)

    def test_cfg03_custom_stances(self):
        """测试 3: 自定义立场（如低糖优先 / 高蛋白优先）正确注入发言实体"""
        t0 = time.perf_counter()
        req = DebateRequest(
            taste="咸鲜",
            budget=50,
            weather="阴",
            spicy_stance="高蛋白肉食优先",
            healthy_stance="低糖轻卡素食优先"
        )
        session = DebateSession(id="test_stances", request=req)
        sp1 = _fallback_speech(session, req.spicy_name, req.spicy_stance, None)
        sp2 = _fallback_speech(session, req.healthy_name, req.healthy_stance, None)
        cost = (time.perf_counter() - t0) * 1000

        ok = (
            sp1.stance == "高蛋白肉食优先" and
            "保持高蛋白肉食优先立场" in sp1.reason and
            sp2.stance == "低糖轻卡素食优先" and
            "保持低糖轻卡素食优先立场" in sp2.reason
        )
        REPORT.log("CFG03", "可配置辩论立场注入发言与论证逻辑", ok, "", cost)
        self.assertTrue(ok)

    def test_cfg04_custom_personas_no_cross(self):
        """测试 4: 两种截然不同的人设风格互不串台"""
        t0 = time.perf_counter()
        req = DebateRequest(
            taste="酸甜",
            budget=35,
            weather="晴",
            spicy_persona="朋克摇滚料理人，态度张扬直接",
            healthy_persona="禅宗寺院素食大师，言辞清幽内敛"
        )
        session = DebateSession(id="test_persona", request=req)
        sp1 = _fallback_speech(session, req.spicy_name, req.spicy_stance, None)
        sp2 = _fallback_speech(session, req.healthy_name, req.healthy_stance, None)
        cost = (time.perf_counter() - t0) * 1000

        ok = (
            "朋克摇滚料理人" in sp1.reason and
            "禅宗寺院素食大师" not in sp1.reason and
            "禅宗寺院素食大师" in sp2.reason and
            "朋克摇滚料理人" not in sp2.reason
        )
        REPORT.log("CFG04", "双方个性化人设风格隔离互不串台", ok, "", cost)
        self.assertTrue(ok)

    def test_cfg05_menu_constraints_priority(self):
        """测试 5: 提供候选菜单时优先/必须从菜单菜品中选择"""
        t0 = time.perf_counter()
        req = DebateRequest(
            taste="甜",
            budget=25,
            weather="晴",
            menu="菜品：杨枝甘露；价格：25\n菜品：芒果班戟；价格：22"
        )
        session = DebateSession(id="test_menu_constraint", request=req)
        sp = _fallback_speech(session, req.spicy_name, req.spicy_stance, None)
        cost = (time.perf_counter() - t0) * 1000

        # 推荐菜必须来自候选菜单第一道菜
        ok = (sp.recommend == "杨枝甘露")
        REPORT.log("CFG05", "候选菜单对大厨推荐菜品的严格约束", ok, "", cost)
        self.assertTrue(ok)

    def test_cfg06_menu_csv_categories(self):
        """测试 6: menu.csv 样例数据多品类识别与覆盖度校验"""
        t0 = time.perf_counter()
        with open("menu.csv", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            categories = {row.get("分类", "").strip() for row in reader}

        required_categories = {"川菜", "甜品", "烧烤", "面食", "盖浇饭", "奶茶", "家常菜"}
        cost = (time.perf_counter() - t0) * 1000

        ok = required_categories.issubset(categories)
        REPORT.log("CFG06", "menu.csv 核心品类完备性覆盖测试", ok, f"missing={required_categories - categories}", cost)
        self.assertTrue(ok)


if __name__ == "__main__":
    suite = unittest.TestLoader().loadTestsFromTestCase(TestAgentConfig)
    unittest.TextTestRunner(verbosity=0).run(suite)
    success = REPORT.print_summary()
    sys.exit(0 if success else 1)
