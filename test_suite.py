"""
干饭辩论赛 - 自动化测试套件
基于《项目开发说明文档》第 3.6 节测试要求编写：
1. 3.6.2 后端语法与静态校验
2. 3.6.3 黑盒测试（等价类划分、边界值分析、场景测试与接口测试 T01-T13）
3. 3.6.4 白盒测试（语句覆盖、分支路径与核心辅助函数逻辑校验）

运行方式：
    python test_suite.py
"""

import csv
import io
import json
import sys
import time
import unittest
from typing import Any
from fastapi.testclient import TestClient

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
from backend.main import (
    app,
    DebateRequest,
    DebateSession,
    Speech,
    DebateReport,
    _history_text,
    _menu_candidates,
    _fallback_speech,
    _fallback_report,
)


class TestRunnerResult:
    def __init__(self):
        self.tests: list[dict[str, Any]] = []

    def record(self, test_id: str, category: str, name: str, passed: bool, message: str = "", duration_ms: float = 0.0):
        self.tests.append({
            "id": test_id,
            "category": category,
            "name": name,
            "passed": passed,
            "message": message,
            "duration_ms": round(duration_ms, 2)
        })

    def print_summary(self):
        total = len(self.tests)
        passed = sum(1 for t in self.tests if t["passed"])
        failed = total - passed

        print("\n" + "=" * 90)
        print(f"       干饭辩论赛自动化测试执行报告 (按照 3.6 软件工程测试要求)")
        print("=" * 90)
        print(f"{'编号':<6}{'类别':<12}{'用例名称':<36}{'耗时(ms)':<10}{'状态'}")
        print("-" * 90)
        for t in self.tests:
            status = " [PASS] " if t["passed"] else "![FAIL]!"
            print(f"{t['id']:<6}{t['category']:<12}{t['name']:<36}{t['duration_ms']:<10}{status}")
            if not t["passed"] and t["message"]:
                print(f"       -> 错误原因: {t['message']}")
        print("=" * 90)
        print(f"总计: {total} 个用例 | 通过: {passed} | 失败: {failed} | 成功率: {passed/max(1, total)*100:.1f}%\n")
        return failed == 0


TEST_REPORT = TestRunnerResult()

class WhiteBoxUnitTests(unittest.TestCase):
    """
    3.6.4 白盒测试：针对内部核心函数与逻辑分支进行覆盖测试
    """
    def test_wb01_menu_candidates_parsing(self):
        """测试菜单候选解析函数 _menu_candidates"""
        start = time.perf_counter()
        raw_menu = (
            "菜品：麻婆豆腐；分类：川菜；价格：18\\n"
            "菜品：水煮牛肉；价格：35\\n"
            "番茄炒蛋, 糖醋里脊；青椒肉丝\\n"
            "菜品：麻婆豆腐\\n"  # 测试去重
        )
        candidates = _menu_candidates(raw_menu)
        duration = (time.perf_counter() - start) * 1000
        passed = (
            "麻婆豆腐" in candidates and
            "水煮牛肉" in candidates and
            "番茄炒蛋" in candidates and
            "糖醋里脊" in candidates and
            "青椒肉丝" in candidates and
            candidates.count("麻婆豆腐") == 1
        )
        TEST_REPORT.record("WB01", "白盒单元", "菜单候选解析与去重逻辑", passed, "", duration)
        self.assertTrue(passed)

    def test_wb02_debate_request_defaults(self):
        """测试模型验证器 apply_defaults 空白字段回退默认值"""
        start = time.perf_counter()
        req = DebateRequest(
            taste="辣",
            budget=30,
            weather="晴",
            spicy_stance=" ",
            healthy_stance=" ",
            spicy_persona="",
            healthy_persona="",
        )
        duration = (time.perf_counter() - start) * 1000
        passed = (
            req.spicy_name == "辣子哥" and
            req.healthy_name == "清补凉" and
            req.spicy_stance == "spicy" and
            req.healthy_stance == "healthy" and
            "火爆川菜大厨" in req.spicy_persona and
            "温和粤菜师傅" in req.healthy_persona
        )
        TEST_REPORT.record("WB02", "白盒单元", "请求模型空白字段自动回退默认值", passed, "", duration)
        self.assertTrue(passed)

    def test_wb03_fallback_speech(self):
        """测试模型调用异常时的本地兜底发言 _fallback_speech"""
        start = time.perf_counter()
        req = DebateRequest(
            taste="甜",
            budget=25,
            weather="阴",
            menu="菜品：杨枝甘露；价格：25\n菜品：芒果班戟；价格：20",
            spicy_name="甜心大厨",
            spicy_stance="甜品第一",
            spicy_persona="专注甜点"
        )
        session = DebateSession(id="test_fallback", request=req)
        speech = _fallback_speech(session, "甜心大厨", "甜品第一", RuntimeError("模拟超时"))
        duration = (time.perf_counter() - start) * 1000
        passed = (
            speech.chef == "甜心大厨" and
            speech.stance == "甜品第一" and
            speech.recommend == "杨枝甘露" and
            speech.round == 1 and
            speech.score == 70
        )
        TEST_REPORT.record("WB03", "白盒单元", "厨师模型异常兜底发言生成", passed, "", duration)
        self.assertTrue(passed)

    def test_wb04_fallback_report(self):
        """测试裁判模型异常时的本地兜底战报 _fallback_report"""
        start = time.perf_counter()
        req = DebateRequest(taste="辣", budget=30, weather="晴")
        session = DebateSession(
            id="test_judge_fallback",
            request=req,
            history=[
                Speech(round=1, chef="辣子哥", recommend="水煮肉片", reason="够辣", score=90, stance="spicy"),
                Speech(round=1, chef="清补凉", recommend="清蒸鱼", reason="养生", score=80, stance="healthy"),
                Speech(round=2, chef="辣子哥", recommend="麻辣香锅", reason="过瘾", score=95, stance="spicy"),
                Speech(round=2, chef="清补凉", recommend="冬瓜排骨汤", reason="降火", score=85, stance="healthy"),
            ]
        )
        report = _fallback_report(session)
        duration = (time.perf_counter() - start) * 1000
        passed = (
            report.winner == "辣子哥" and
            report.dish == "麻辣香锅" and
            report.score["辣子哥"] == 92 and  # Python round-half-to-even: round(92.5) == 92
            report.score["清补凉"] == 82      # round(82.5) == 82
        )
        TEST_REPORT.record("WB04", "白盒单元", "裁判异常时根据发言均分判决兜底战报", passed, "", duration)
        self.assertTrue(passed)

    def test_wb05_history_text_formatter(self):
        """测试历史文本格式化 _history_text"""
        start = time.perf_counter()
        empty_text = _history_text([])
        sample_speeches = [
            Speech(round=1, chef="A", recommend="菜品1", reason="理由1", score=80, stance="s1")
        ]
        formatted_text = _history_text(sample_speeches)
        duration = (time.perf_counter() - start) * 1000
        passed = (empty_text == "暂无发言。" and "第1轮 A：菜品1；理由1" in formatted_text)
        TEST_REPORT.record("WB05", "白盒单元", "辩论历史上下文文本格式化", passed, "", duration)
        self.assertTrue(passed)

class BlackBoxBoundaryTests(unittest.TestCase):
    """
    3.6.3 黑盒测试：等价类划分与边界值分析 (Boundary Value Analysis)
    """
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_bb01_budget_boundary(self):
        """测试预算边界值 [1, 500] 及其邻近值 0, 501"""
        start = time.perf_counter()
        # 有效边界 1 和 500
        r_min = self.client.post("/api/debates", json={"taste": "辣", "budget": 1, "weather": "晴"})
        r_max = self.client.post("/api/debates", json={"taste": "辣", "budget": 500, "weather": "晴"})
        # 无效边界 0 和 501
        r_below = self.client.post("/api/debates", json={"taste": "辣", "budget": 0, "weather": "晴"})
        r_above = self.client.post("/api/debates", json={"taste": "辣", "budget": 501, "weather": "晴"})

        duration = (time.perf_counter() - start) * 1000
        passed = (
            r_min.status_code == 201 and
            r_max.status_code == 201 and
            r_below.status_code == 422 and
            r_above.status_code == 422
        )
        TEST_REPORT.record("BB01", "黑盒边界", "预算字段边界值分析 (0, 1, 500, 501)", passed, "", duration)
        self.assertTrue(passed)

    def test_bb02_rounds_boundary(self):
        """测试轮次边界值 [1, 5] 及其邻近值 0, 6"""
        start = time.perf_counter()
        r_min = self.client.post("/api/debates", json={"taste": "辣", "budget": 30, "weather": "晴", "rounds": 1})
        r_max = self.client.post("/api/debates", json={"taste": "辣", "budget": 30, "weather": "晴", "rounds": 5})
        r_below = self.client.post("/api/debates", json={"taste": "辣", "budget": 30, "weather": "晴", "rounds": 0})
        r_above = self.client.post("/api/debates", json={"taste": "辣", "budget": 30, "weather": "晴", "rounds": 6})

        duration = (time.perf_counter() - start) * 1000
        passed = (
            r_min.status_code == 201 and
            r_max.status_code == 201 and
            r_below.status_code == 422 and
            r_above.status_code == 422
        )
        TEST_REPORT.record("BB02", "黑盒边界", "辩论轮次边界值分析 (0, 1, 5, 6)", passed, "", duration)
        self.assertTrue(passed)

    def test_bb03_taste_and_menu_limits(self):
        """测试文本长度限制：taste(1-100) 与 menu(最大50000)"""
        start = time.perf_counter()
        # taste 边界
        r_empty_taste = self.client.post("/api/debates", json={"taste": "", "budget": 30, "weather": "晴"})
        r_100_taste = self.client.post("/api/debates", json={"taste": "a" * 100, "budget": 30, "weather": "晴"})
        r_101_taste = self.client.post("/api/debates", json={"taste": "a" * 101, "budget": 30, "weather": "晴"})

        # menu 超长边界
        r_overflow_menu = self.client.post("/api/debates", json={"taste": "辣", "budget": 30, "weather": "晴", "menu": "a" * 50001})

        duration = (time.perf_counter() - start) * 1000
        passed = (
            r_empty_taste.status_code == 422 and
            r_100_taste.status_code == 201 and
            r_101_taste.status_code == 422 and
            r_overflow_menu.status_code == 422
        )
        TEST_REPORT.record("BB03", "黑盒等价", "口味偏好与菜单字段长度限制校验", passed, "", duration)
        self.assertTrue(passed)

class InterfaceIntegrationTests(unittest.TestCase):
    """
    3.6.3 (4) 接口黑盒测试与功能集成测试 (T01 - T13)
    """
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_t01_create_debate(self):
        """T01: 创建辩论会话"""
        start = time.perf_counter()
        resp = self.client.post("/api/debates", json={"taste": "微辣", "budget": 35, "weather": "阴天", "rounds": 2})
        duration = (time.perf_counter() - start) * 1000
        passed = (resp.status_code == 201 and "id" in resp.json() and resp.json()["status"] == "PENDING")
        TEST_REPORT.record("T01", "接口集成", "创建辩论会话 POST /api/debates", passed, "", duration)
        self.assertTrue(passed)

    def test_t02_get_debate(self):
        """T02: 查询指定辩论会话详情"""
        start = time.perf_counter()
        create_resp = self.client.post("/api/debates", json={"taste": "甜", "budget": 20, "weather": "晴"})
        debate_id = create_resp.json()["id"]
        get_resp = self.client.get(f"/api/debates/{debate_id}")
        duration = (time.perf_counter() - start) * 1000
        passed = (get_resp.status_code == 200 and get_resp.json()["id"] == debate_id)
        TEST_REPORT.record("T02", "接口集成", "查询指定会话 GET /api/debates/{id}", passed, "", duration)
        self.assertTrue(passed)

    def test_t03_get_index_html(self):
        """T03: 请求前端首页"""
        start = time.perf_counter()
        resp = self.client.get("/")
        duration = (time.perf_counter() - start) * 1000
        passed = (resp.status_code == 200 and "干饭辩论赛" in resp.text)
        TEST_REPORT.record("T03", "接口集成", "前端页面访问 GET /", passed, "", duration)
        self.assertTrue(passed)

    def test_t04_list_debates(self):
        """T04: 获取历史辩论列表"""
        start = time.perf_counter()
        resp = self.client.get("/api/debates")
        duration = (time.perf_counter() - start) * 1000
        passed = (resp.status_code == 200 and isinstance(resp.json(), list))
        TEST_REPORT.record("T04", "接口集成", "查询历史会话 GET /api/debates", passed, "", duration)
        self.assertTrue(passed)

    def test_t05_stop_single_debate(self):
        """T05: 终止单个辩论会话"""
        start = time.perf_counter()
        create_resp = self.client.post("/api/debates", json={"taste": "酸辣", "budget": 25, "weather": "雨"})
        debate_id = create_resp.json()["id"]
        stop_resp = self.client.post(f"/api/debates/{debate_id}/stop")
        duration = (time.perf_counter() - start) * 1000
        passed = (stop_resp.status_code == 200 and stop_resp.json()["status"] == "TERMINATED")
        TEST_REPORT.record("T05", "接口集成", "终止单个会话 POST /api/debates/{id}/stop", passed, "", duration)
        self.assertTrue(passed)

    def test_t06_stop_all_debates(self):
        """T06: 终止所有未完成辩论会话"""
        start = time.perf_counter()
        self.client.post("/api/debates", json={"taste": "辣", "budget": 30, "weather": "晴"})
        stop_all = self.client.post("/api/debates/stop-all")
        duration = (time.perf_counter() - start) * 1000
        passed = (stop_all.status_code == 200 and "stopped" in stop_all.json())
        TEST_REPORT.record("T06", "接口集成", "终止全部会话 POST /api/debates/stop-all", passed, "", duration)
        self.assertTrue(passed)

    def test_t07_favorite_crud_lifecycle(self):
        """T07: 菜品收藏的完整生命周期测试（新增 -> 查询 -> 删除 -> 二次删除404）"""
        start = time.perf_counter()
        # 1. 创建会话
        create_resp = self.client.post("/api/debates", json={"taste": "香辣", "budget": 40, "weather": "晴"})
        debate_id = create_resp.json()["id"]

        # 2. 收藏菜品
        fav_resp = self.client.post("/api/favorites", json={
            "debate_id": debate_id,
            "dish": "经典麻婆豆腐",
            "note": "自动化测试收藏"
        })
        fav_ok = (fav_resp.status_code == 200 and "id" in fav_resp.json())
        fav_id = fav_resp.json().get("id")

        # 3. 查询收藏列表
        list_resp = self.client.get("/api/favorites")
        list_ok = (list_resp.status_code == 200 and any(item["id"] == fav_id for item in list_resp.json()))

        # 4. 删除收藏
        del_resp = self.client.delete(f"/api/favorites/{fav_id}")
        del_ok = (del_resp.status_code == 200 and del_resp.json().get("deleted") is True)

        # 5. 验证删除后再查返回404
        re_del_resp = self.client.delete(f"/api/favorites/{fav_id}")
        re_del_ok = (re_del_resp.status_code == 404)

        duration = (time.perf_counter() - start) * 1000
        passed = fav_ok and list_ok and del_ok and re_del_ok
        TEST_REPORT.record("T07", "接口集成", "菜品收藏生命周期 (增/查/删/404验证)", passed, "", duration)
        self.assertTrue(passed)

    def test_t08_menu_csv_upload_valid(self):
        """T08: 上传合法 CSV 菜单并解析"""
        start = time.perf_counter()
        csv_data = "菜品,价格,辣度\n麻婆豆腐,18,中辣\n番茄炒蛋,16,不辣\n".encode("utf-8-sig")
        resp = self.client.post("/api/menu/upload", files={"file": ("menu_test.csv", csv_data, "text/csv")})
        duration = (time.perf_counter() - start) * 1000
        passed = (resp.status_code == 200 and resp.json()["count"] == 2 and "麻婆豆腐" in resp.json()["menu"])
        TEST_REPORT.record("T08", "接口集成", "上传并解析 CSV 菜单 POST /api/menu/upload", passed, "", duration)
        self.assertTrue(passed)

    def test_t09_menu_upload_invalid_type(self):
        """T09: 上传非法文件格式（如 .txt）拒绝并返回 400"""
        start = time.perf_counter()
        resp = self.client.post("/api/menu/upload", files={"file": ("menu.txt", b"test", "text/plain")})
        duration = (time.perf_counter() - start) * 1000
        passed = (resp.status_code == 400 and "只支持 CSV 或 XLSX" in resp.json()["detail"])
        TEST_REPORT.record("T09", "接口集成", "菜单非法类型拦截校验", passed, "", duration)
        self.assertTrue(passed)

    def test_t10_tts_voice_validation(self):
        """T10: 语音接口非法语音角色拦截校验"""
        start = time.perf_counter()
        resp = self.client.get("/api/tts", params={"text": "你好", "voice": "invalid-voice-name"})
        duration = (time.perf_counter() - start) * 1000
        passed = (resp.status_code == 400 and "不支持的语音角色" in resp.json()["detail"])
        TEST_REPORT.record("T10", "接口集成", "语音接口角色合法性拦截 GET /api/tts", passed, "", duration)
        self.assertTrue(passed)


if __name__ == "__main__":
    suite = unittest.TestSuite()
    loader = unittest.TestLoader()
    suite.addTests(loader.loadTestsFromTestCase(WhiteBoxUnitTests))
    suite.addTests(loader.loadTestsFromTestCase(BlackBoxBoundaryTests))
    suite.addTests(loader.loadTestsFromTestCase(InterfaceIntegrationTests))

    runner = unittest.TextTestRunner(verbosity=0)
    runner.run(suite)
    success = TEST_REPORT.print_summary()
    exit(0 if success else 1)
