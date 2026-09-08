# test_blackbox_interfaces.py
"""
黑盒接口测试 (T01 - T13)
基于《项目开发说明文档》3.6.3 接口黑盒测试表开发
"""

import io
import sys
import time
import unittest
from fastapi.testclient import TestClient

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from unittest.mock import AsyncMock, patch
from backend.main import app, Speech, DebateReport


class BlackboxInterfaceReport:
    def __init__(self):
        self.records = []

    def log(self, tid, name, passed, message="", cost_ms=0.0):
        self.records.append({
            "id": tid,
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
        print("          接口黑盒测试执行报告 (T01 - T13)")
        print("=" * 90)
        print(f"{'编号':<6}{'测试内容':<28}{'耗时(ms)':<10}{'状态'}")
        print("-" * 90)
        for r in self.records:
            status = " [PASS] " if r["passed"] else "![FAIL]!"
            print(f"{r['id']:<6}{r['name']:<28}{r['cost_ms']:<10}{status}")
            if not r["passed"] and r["message"]:
                print(f"       -> 错误原因: {r['message']}")
        print("=" * 90)
        print(f"总计: {total} 个用例 | 通过: {passed} | 失败: {failed} | 成功率: {passed/max(1, total)*100:.1f}%\n")
        return failed == 0


REPORT = BlackboxInterfaceReport()


class TestBlackboxInterfaces(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_t01_create_debate(self):
        """T01: 创建会话 POST /api/debates -> 201 和会话 ID"""
        t0 = time.perf_counter()
        resp = self.client.post("/api/debates", json={"taste": "微辣", "budget": 30, "weather": "晴天"})
        cost = (time.perf_counter() - t0) * 1000
        ok = resp.status_code == 201 and "id" in resp.json() and resp.json()["status"] == "PENDING"
        REPORT.log("T01", "创建会话", ok, resp.text if not ok else "", cost)
        self.assertTrue(ok)

    def test_t02_get_debate(self):
        """T02: 查询会话 GET /api/debates/{id} -> 状态和历史"""
        t0 = time.perf_counter()
        c_resp = self.client.post("/api/debates", json={"taste": "甜", "budget": 20, "weather": "阴天"})
        did = c_resp.json()["id"]
        resp = self.client.get(f"/api/debates/{did}")
        cost = (time.perf_counter() - t0) * 1000
        ok = resp.status_code == 200 and resp.json()["id"] == did and "history" in resp.json()
        REPORT.log("T02", "查询会话", ok, resp.text if not ok else "", cost)
        self.assertTrue(ok)

    def test_t03_start_sse(self):
        """T03: 开始 SSE GET /api/debates/{id}/stream -> 200 和事件流"""
        t0 = time.perf_counter()
        c_resp = self.client.post("/api/debates", json={"taste": "微酸", "budget": 25, "weather": "晴", "rounds": 1})
        did = c_resp.json()["id"]

        mock_speech = Speech(round=1, chef="辣子哥", recommend="水煮肉片", reason="够辣", score=90, stance="spicy")
        mock_report = DebateReport(winner="辣子哥", dish="水煮肉片", score={"辣子哥": 90, "清补凉": 80}, summary="胜出", barrage="弹幕")

        with patch("backend.main._call_chef", new_callable=AsyncMock, return_value=mock_speech), \
             patch("backend.main._call_judge", new_callable=AsyncMock, return_value=mock_report):
            with self.client.stream("GET", f"/api/debates/{did}/stream") as response:
                status_ok = response.status_code == 200
                ct_ok = "text/event-stream" in response.headers.get("content-type", "")
                first_chunk = next(response.iter_lines())
                event_ok = "event:" in first_chunk or "data:" in first_chunk

        cost = (time.perf_counter() - t0) * 1000
        ok = status_ok and ct_ok and event_ok
        REPORT.log("T03", "开始 SSE 流", ok, f"status={response.status_code}", cost)
        self.assertTrue(ok)

    def test_t04_rounds_boundary(self):
        """T04: 轮数边界 rounds=0/6 返回 422"""
        t0 = time.perf_counter()
        r0 = self.client.post("/api/debates", json={"taste": "辣", "budget": 30, "weather": "晴", "rounds": 0})
        r6 = self.client.post("/api/debates", json={"taste": "辣", "budget": 30, "weather": "晴", "rounds": 6})
        cost = (time.perf_counter() - t0) * 1000
        ok = r0.status_code == 422 and r6.status_code == 422
        REPORT.log("T04", "轮数边界校验 (0/6)", ok, f"r0={r0.status_code}, r6={r6.status_code}", cost)
        self.assertTrue(ok)

    def test_t05_empty_required_fields(self):
        """T05: 空必填字段 空口味或空天气返回 422"""
        t0 = time.perf_counter()
        r_taste = self.client.post("/api/debates", json={"taste": "", "budget": 30, "weather": "晴"})
        r_weather = self.client.post("/api/debates", json={"taste": "辣", "budget": 30, "weather": ""})
        cost = (time.perf_counter() - t0) * 1000
        ok = r_taste.status_code == 422 and r_weather.status_code == 422
        REPORT.log("T05", "空必填字段拦截", ok, f"taste={r_taste.status_code}, weather={r_weather.status_code}", cost)
        self.assertTrue(ok)

    def test_t06_list_debates(self):
        """T06: 历史列表 GET /api/debates -> SQLite 中的会话列表"""
        t0 = time.perf_counter()
        resp = self.client.get("/api/debates")
        cost = (time.perf_counter() - t0) * 1000
        ok = resp.status_code == 200 and isinstance(resp.json(), list)
        REPORT.log("T06", "查询历史会话列表", ok, resp.text if not ok else "", cost)
        self.assertTrue(ok)

    def test_t07_stop_debate(self):
        """T07: 终止会话 POST /api/debates/{id}/stop -> 状态变为 TERMINATED"""
        t0 = time.perf_counter()
        c_resp = self.client.post("/api/debates", json={"taste": "重辣", "budget": 35, "weather": "阴"})
        did = c_resp.json()["id"]
        s_resp = self.client.post(f"/api/debates/{did}/stop")
        cost = (time.perf_counter() - t0) * 1000
        ok = s_resp.status_code == 200 and s_resp.json()["status"] == "TERMINATED"
        REPORT.log("T07", "终止会话", ok, s_resp.text if not ok else "", cost)
        self.assertTrue(ok)

    def test_t08_add_favorite(self):
        """T08: 收藏菜品 POST /api/favorites -> 返回收藏记录"""
        t0 = time.perf_counter()
        c_resp = self.client.post("/api/debates", json={"taste": "微辣", "budget": 20, "weather": "晴"})
        did = c_resp.json()["id"]
        f_resp = self.client.post("/api/favorites", json={"debate_id": did, "dish": "麻婆豆腐", "note": "收藏测试"})
        cost = (time.perf_counter() - t0) * 1000
        ok = f_resp.status_code == 200 and "id" in f_resp.json() and f_resp.json()["dish"] == "麻婆豆腐"
        REPORT.log("T08", "收藏菜品", ok, f_resp.text if not ok else "", cost)
        self.assertTrue(ok)

    def test_t09_list_favorites(self):
        """T09: 查询收藏 GET /api/favorites -> 返回收藏列表"""
        t0 = time.perf_counter()
        resp = self.client.get("/api/favorites")
        cost = (time.perf_counter() - t0) * 1000
        ok = resp.status_code == 200 and isinstance(resp.json(), list)
        REPORT.log("T09", "查询收藏列表", ok, resp.text if not ok else "", cost)
        self.assertTrue(ok)

    def test_t10_delete_favorite(self):
        """T10: 删除收藏 DELETE /api/favorites/{id} -> deleted=true"""
        t0 = time.perf_counter()
        c_resp = self.client.post("/api/debates", json={"taste": "甜", "budget": 15, "weather": "雨"})
        did = c_resp.json()["id"]
        f_resp = self.client.post("/api/favorites", json={"debate_id": did, "dish": "扬枝甘露"})
        fid = f_resp.json()["id"]

        del_resp = self.client.delete(f"/api/favorites/{fid}")
        cost = (time.perf_counter() - t0) * 1000
        ok = del_resp.status_code == 200 and del_resp.json().get("deleted") is True
        REPORT.log("T10", "删除收藏", ok, del_resp.text if not ok else "", cost)
        self.assertTrue(ok)

    def test_t11_tts_endpoint(self):
        """T11: 语音接口参数拦截与合法性校验 GET /api/tts"""
        t0 = time.perf_counter()
        # 错误语音角色测试
        err_resp = self.client.get("/api/tts", params={"text": "测试", "voice": "unknown-voice"})
        # 空文本拦截测试
        empty_resp = self.client.get("/api/tts", params={"text": "   ", "voice": "zh-CN-YunxiNeural"})
        cost = (time.perf_counter() - t0) * 1000
        ok = err_resp.status_code == 400 and empty_resp.status_code == 400
        REPORT.log("T11", "语音接口参数校验", ok, f"err={err_resp.status_code}, empty={empty_resp.status_code}", cost)
        self.assertTrue(ok)

    def test_t12_upload_csv(self):
        """T12: 上传 CSV POST /api/menu/upload -> 菜单条数和候选文本"""
        t0 = time.perf_counter()
        csv_bytes = "菜品,价格,辣度\n麻婆豆腐,18,中辣\n宫保鸡丁,24,微辣\n".encode("utf-8-sig")
        resp = self.client.post("/api/menu/upload", files={"file": ("menu_t12.csv", csv_bytes, "text/csv")})
        cost = (time.perf_counter() - t0) * 1000
        ok = resp.status_code == 200 and resp.json().get("count") == 2 and "麻婆豆腐" in resp.json().get("menu", "")
        REPORT.log("T12", "上传 CSV 菜单", ok, resp.text if not ok else "", cost)
        self.assertTrue(ok)

    def test_t13_upload_xlsx(self):
        """T13: 上传 XLSX POST /api/menu/upload -> 菜单条数和候选文本"""
        t0 = time.perf_counter()
        try:
            from openpyxl import Workbook
            wb = Workbook()
            ws = wb.active
            ws.append(["菜品", "价格", "辣度"])
            ws.append(["红烧肉", "28", "不辣"])
            ws.append(["水煮鱼", "35", "中辣"])
            buf = io.BytesIO()
            wb.save(buf)
            xlsx_bytes = buf.getvalue()

            resp = self.client.post(
                "/api/menu/upload",
                files={"file": ("menu_t13.xlsx", xlsx_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
            )
            ok = resp.status_code == 200 and resp.json().get("count") == 2 and "红烧肉" in resp.json().get("menu", "")
        except Exception as e:
            ok = False
            resp = type("obj", (), {"text": str(e)})()

        cost = (time.perf_counter() - t0) * 1000
        REPORT.log("T13", "上传 XLSX 菜单", ok, getattr(resp, "text", ""), cost)
        self.assertTrue(ok)


if __name__ == "__main__":
    suite = unittest.TestLoader().loadTestsFromTestCase(TestBlackboxInterfaces)
    unittest.TextTestRunner(verbosity=0).run(suite)
    success = REPORT.print_summary()
    sys.exit(0 if success else 1)
