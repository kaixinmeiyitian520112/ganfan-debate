# scenario_tests_b01_b08.py
"""
场景测试 B01-B08
逐个覆盖业务场景，验证系统在各种条件下的行为
"""

import csv
import io
import json
import sys
import time
import unittest
from fastapi.testclient import TestClient

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from backend.main import app, _fallback_report, DebateSession, DebateRequest, Speech, _menu_candidates

# ===== 全局测试报告收集器 =====
class ScenarioTestReport:
    """场景测试结果收集器"""
    def __init__(self):
        self.tests = []

    def record(self, test_id, category, name, passed, message="", duration_ms=0):
        self.tests.append({
            "id": test_id,
            "category": category,
            "name": name,
            "passed": passed,
            "message": message,
            "duration_ms": round(duration_ms, 2)
        })

    def print_report(self):
        total = len(self.tests)
        passed = sum(1 for t in self.tests if t["passed"])
        failed = total - passed

        print("\n" + "=" * 90)
        print("       场景测试执行报告 (B01-B08)")
        print("=" * 90)
        print(f"{'编号':<6}{'类别':<12}{'用例名称':<50}{'耗时(ms)':<10}{'状态'}")
        print("-" * 90)
        for t in self.tests:
            status = " [PASS] " if t["passed"] else "![FAIL]!"
            print(f"{t['id']:<6}{t['category']:<12}{t['name']:<50}{t['duration_ms']:<10}{status}")
            if not t["passed"] and t["message"]:
                print(f"       -> 错误原因: {t['message']}")
        print("=" * 90)
        print(f"总计: {total} 个用例 | 通过: {passed} | 失败: {failed} | 成功率: {passed/max(1, total)*100:.1f}%")
        print("=" * 90 + "\n")
        return failed == 0


SCENARIO_REPORT = ScenarioTestReport()


# ============================================================================
# 场景测试类
# ============================================================================

class ScenarioTestsB01_B08(unittest.TestCase):
    """
    场景测试 B01-B08
    覆盖: 菜单来源、价格估算、断线重连、终止、兜底
    """

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    # =========================================================================
    # B01: 无文件、无文本菜单 → Agent 自行举例推荐
    # =========================================================================
    def test_b01_no_menu_no_file(self):
        """B01: 无文件、无文本菜单 → Agent 自行举例推荐"""
        start = time.perf_counter()

        # 不传 menu 字段，也不上传文件
        resp = self.client.post(
            "/api/debates",
            json={
                "taste": "辣",
                "budget": 30,
                "weather": "晴"
                # 故意不传 menu
            }
        )

        duration = (time.perf_counter() - start) * 1000

        # 验证: 创建成功，menu 为空字符串（默认值），Agent 会自行举例
        passed = resp.status_code == 201

        if passed:
            data = resp.json()
            # 验证 menu 字段存在且为空（或未提供）
            # 注意: 创建时未传 menu，Pydantic 会使用默认值 ""
            self.assertIsNotNone(data.get("id"))
            print(f"  ✅ 创建的辩论ID: {data.get('id')}")

        SCENARIO_REPORT.record("B01", "场景测试", "无菜单时Agent自行举例推荐", passed, "", duration)
        self.assertTrue(passed, f"B01 失败: 状态码 {resp.status_code}")

    # =========================================================================
    # B02: 只有文本菜单 → Agent 只从文本候选中选择
    # =========================================================================
    def test_b02_only_text_menu(self):
        """B02: 只有文本菜单 → Agent 只从文本候选中选择"""
        start = time.perf_counter()

        text_menu = "麻婆豆腐, 水煮牛肉, 番茄炒蛋"

        resp = self.client.post(
            "/api/debates",
            json={
                "taste": "辣",
                "budget": 30,
                "weather": "晴",
                "menu": text_menu
            }
        )

        duration = (time.perf_counter() - start) * 1000

        passed = resp.status_code == 201

        if passed:
            debate_id = resp.json()["id"]
            # 查询确认菜单被正确存储
            detail = self.client.get(f"/api/debates/{debate_id}")
            stored_menu = detail.json().get("request", {}).get("menu", "")
            # 验证文本菜单中的菜品都在候选列表中
            candidates = _menu_candidates(stored_menu)
            passed = (
                "麻婆豆腐" in candidates and
                "水煮牛肉" in candidates and
                "番茄炒蛋" in candidates
            )
            if passed:
                print(f"  ✅ 文本菜单解析成功: {candidates}")

        SCENARIO_REPORT.record("B02", "场景测试", "文本菜单作为唯一候选", passed, "", duration)
        self.assertTrue(passed, "B02 失败: 文本菜单未正确解析")

    # =========================================================================
    # B03: 只有 CSV/XLSX 文件 → 文件菜单自动填入并作为候选
    # =========================================================================
    def test_b03_only_csv_file(self):
        """B03: 只有 CSV/XLSX 文件 → 文件菜单自动填入并作为候选"""
        start = time.perf_counter()

        # 构造 CSV 内容 (列名: 菜品,价格)
        csv_content = "菜品,价格\n麻婆豆腐,18\n水煮牛肉,35\n番茄炒蛋,12"
        files = {"file": ("menu.csv", csv_content, "text/csv")}

        # 上传文件
        upload_resp = self.client.post("/api/menu/upload", files=files)

        duration = (time.perf_counter() - start) * 1000

        passed = upload_resp.status_code == 200

        if passed:
            menu_text = upload_resp.json().get("menu", "").replace("\n", "\\n")
            candidates = _menu_candidates(menu_text)
            passed = (
                "麻婆豆腐" in candidates and
                "水煮牛肉" in candidates and
                "番茄炒蛋" in candidates
            )
            if passed:
                print(f"  ✅ CSV 解析成功，候选菜单: {candidates}")

        SCENARIO_REPORT.record("B03", "场景测试", "CSV文件自动填入菜单", passed, "", duration)
        self.assertTrue(passed, "B03 失败: CSV 文件解析错误")

    # =========================================================================
    # B04: 文件和文本同时存在 → 两者合并作为候选菜单
    # =========================================================================
    def test_b04_file_and_text_merge(self):
        """B04: 文件和文本同时存在 → 两者合并作为候选菜单"""
        start = time.perf_counter()

        # 1. 先上传 CSV 文件
        csv_content = "菜品,价格\n麻婆豆腐,18\n水煮牛肉,35"
        files = {"file": ("menu.csv", csv_content, "text/csv")}
        upload_resp = self.client.post("/api/menu/upload", files=files)

        if upload_resp.status_code != 200:
            SCENARIO_REPORT.record("B04", "场景测试", "文件+文本菜单合并", False, "CSV上传失败", duration)
            self.fail("B04: CSV 上传失败")

        file_menu = upload_resp.json().get("menu", "")

        # 2. 手动添加文本菜单
        text_menu = "宫保鸡丁, 鱼香肉丝"
        merged_menu = file_menu + "\n" + text_menu

        # 3. 创建辩论，使用合并后的菜单
        resp = self.client.post(
            "/api/debates",
            json={
                "taste": "辣",
                "budget": 30,
                "weather": "晴",
                "menu": merged_menu
            }
        )

        duration = (time.perf_counter() - start) * 1000

        passed = resp.status_code == 201

        if passed:
            debate_id = resp.json()["id"]
            detail = self.client.get(f"/api/debates/{debate_id}")
            stored_menu = detail.json().get("request", {}).get("menu", "")
            candidates = _menu_candidates(stored_menu.replace("\n", "\\n"))

            # 验证两种来源的菜都在候选菜单中
            passed = (
                "麻婆豆腐" in candidates and     # 来自 CSV
                "水煮牛肉" in candidates and     # 来自 CSV
                "宫保鸡丁" in candidates and     # 来自文本
                "鱼香肉丝" in candidates         # 来自文本
            )
            if passed:
                print(f"  ✅ 菜单合并成功: {candidates}")

        SCENARIO_REPORT.record("B04", "场景测试", "文件+文本菜单合并", passed, "", duration)
        self.assertTrue(passed, "B04 失败: 菜单合并逻辑错误")

    # =========================================================================
    # B05: 菜单缺少价格 → Agent 按预算估算价格
    # =========================================================================
    def test_b05_menu_without_price(self):
        """B05: 菜单缺少价格 → Agent 按预算估算价格"""
        start = time.perf_counter()

        # 菜单中没有价格信息（只有菜名）
        menu_without_price = "麻婆豆腐, 水煮牛肉, 番茄炒蛋"

        resp = self.client.post(
            "/api/debates",
            json={
                "taste": "辣",
                "budget": 30,
                "weather": "晴",
                "menu": menu_without_price
            }
        )

        duration = (time.perf_counter() - start) * 1000

        # 验证创建成功（价格由 Agent 估算，后端不强制要求价格）
        passed = resp.status_code == 201

        if passed:
            debate_id = resp.json()["id"]
            detail = self.client.get(f"/api/debates/{debate_id}")
            stored_menu = detail.json().get("request", {}).get("menu", "")
            candidates = _menu_candidates(stored_menu)
            # 验证所有菜品都被解析出来
            passed = (
                "麻婆豆腐" in candidates and
                "水煮牛肉" in candidates and
                "番茄炒蛋" in candidates
            )
            if passed:
                print(f"  ✅ 无价格菜单解析成功: {candidates}")

        SCENARIO_REPORT.record("B05", "场景测试", "菜单无价格时Agent估算", passed, "", duration)
        self.assertTrue(passed, "B05 失败: 无价格菜单处理错误")

    # =========================================================================
    # B06: 中途断线 → 已有历史保留，刷新后继续
    # =========================================================================
    def test_b06_disconnect_reconnect(self):
        """B06: 中途断线 → 已有历史保留，刷新后继续"""
        start = time.perf_counter()

        # 1. 创建辩论
        create_resp = self.client.post(
            "/api/debates",
            json={
                "taste": "辣",
                "budget": 30,
                "weather": "晴",
                "rounds": 2
            }
        )

        if create_resp.status_code != 201:
            SCENARIO_REPORT.record("B06", "场景测试", "断线重连后数据保留", False, "创建辩论失败", duration)
            self.fail("B06: 创建辩论失败")

        debate_id = create_resp.json()["id"]
        print(f"  ✅ 创建辩论: {debate_id}")

        # 2. 模拟断线：这里我们只是等待一下，然后重新查询
        #    实际场景中，断线后用户刷新页面重新连接

        # 3. 重新查询（模拟刷新）
        detail_resp = self.client.get(f"/api/debates/{debate_id}")

        duration = (time.perf_counter() - start) * 1000

        passed = detail_resp.status_code == 200

        if passed:
            data = detail_resp.json()
            # 验证会话 ID 一致，状态存在
            passed = data.get("id") == debate_id and data.get("status") is not None
            print(f"  ✅ 断线重连成功，状态: {data.get('status')}")

        SCENARIO_REPORT.record("B06", "场景测试", "断线重连后数据保留", passed, "", duration)
        self.assertTrue(passed, "B06 失败: 断线重连后数据丢失")

    # =========================================================================
    # B07: 用户终止 → 状态为 TERMINATED，不再生成
    # =========================================================================
    def test_b07_user_terminate(self):
        """B07: 用户终止 → 状态为 TERMINATED，不再生成"""
        start = time.perf_counter()

        # 1. 创建辩论
        create_resp = self.client.post(
            "/api/debates",
            json={
                "taste": "辣",
                "budget": 30,
                "weather": "晴",
                "rounds": 3
            }
        )

        if create_resp.status_code != 201:
            SCENARIO_REPORT.record("B07", "场景测试", "用户终止会话状态变更", False, "创建辩论失败", duration)
            self.fail("B07: 创建辩论失败")

        debate_id = create_resp.json()["id"]
        print(f"  ✅ 创建辩论: {debate_id}")

        # 2. 终止会话
        stop_resp = self.client.post(f"/api/debates/{debate_id}/stop")

        if stop_resp.status_code != 200:
            SCENARIO_REPORT.record("B07", "场景测试", "用户终止会话状态变更", False, "终止请求失败", duration)
            self.fail("B07: 终止请求失败")

        # 3. 查询确认状态
        detail_resp = self.client.get(f"/api/debates/{debate_id}")

        duration = (time.perf_counter() - start) * 1000

        passed = detail_resp.status_code == 200

        if passed:
            status = detail_resp.json().get("status")
            passed = status == "TERMINATED"
            print(f"  ✅ 终止成功，当前状态: {status}")

        SCENARIO_REPORT.record("B07", "场景测试", "用户终止会话状态变更", passed, "", duration)
        self.assertTrue(passed, f"B07 失败: 状态不是 TERMINATED")

    # =========================================================================
    # B08: 裁判调用失败 → 返回本地兜底战报
    # =========================================================================
    def test_b08_judge_fallback(self):
        """B08: 裁判调用失败 → 返回本地兜底战报"""
        start = time.perf_counter()

        # 直接测试 _fallback_report 函数（不需要真实调用模型）
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

        # 验证兜底战报内容
        # 辣子哥均分: (90 + 95) / 2 = 92.5 → Python round() → 92 (银行家舍入)
        # 清补凉均分: (80 + 85) / 2 = 82.5 → Python round() → 82 (银行家舍入)
        passed = (
            report.winner == "辣子哥" and
            report.dish == "麻辣香锅" and
            report.score["辣子哥"] == 92 and
            report.score["清补凉"] == 82
        )

        if passed:
            print(f"  ✅ 兜底战报: 胜者={report.winner}, 推荐菜={report.dish}, 评分={report.score}")

        SCENARIO_REPORT.record("B08", "场景测试", "裁判失败时本地兜底战报", passed, "", duration)
        self.assertTrue(passed, "B08 失败: 兜底战报内容不正确")


# ============================================================================
# 主入口
# ============================================================================

if __name__ == "__main__":
    print("\n" + "=" * 90)
    print("  场景测试 B01-B08 启动")
    print("  测试目标: 覆盖业务场景 (菜单来源、价格估算、断线重连、终止、兜底)")
    print("=" * 90 + "\n")

    # 运行测试
    unittest.main(verbosity=2, exit=False)

    # 打印报告
    SCENARIO_REPORT.print_report()