# test_security.py
"""
系统安全测试 (3.6.9)
覆盖 XSS 防御、API Key 隔离、输入长度限制、参数化 SQL 注入防御及敏感文件过滤
"""

import os
import sys
import time
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from backend.main import app, _db, FavoriteRequest, add_favorite, sessions


class SecurityReport:
    def __init__(self):
        self.records = []

    def log(self, sid, name, passed, message="", cost_ms=0.0):
        self.records.append({
            "id": sid,
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
        print("          系统安全与注入防御测试执行报告 (3.6.9)")
        print("=" * 90)
        print(f"{'编号':<6}{'测试内容':<42}{'耗时(ms)':<10}{'状态'}")
        print("-" * 90)
        for r in self.records:
            status = " [PASS] " if r["passed"] else "![FAIL]!"
            print(f"{r['id']:<6}{r['name']:<42}{r['cost_ms']:<10}{status}")
            if not r["passed"] and r["message"]:
                print(f"       -> 错误原因: {r['message']}")
        print("=" * 90)
        print(f"总计: {total} 个用例 | 通过: {passed} | 失败: {failed} | 成功率: {passed/max(1, total)*100:.1f}%\n")
        return failed == 0


REPORT = SecurityReport()


class TestSecurity(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_sec01_frontend_xss_protection(self):
        """1. 前端通过 textContent 展示模型文本，避免 innerHTML 脚本注入"""
        t0 = time.perf_counter()
        html_path = os.path.join(os.path.dirname(__file__), "frontend", "index.html")
        with open(html_path, "r", encoding="utf-8") as f:
            html_content = f.read()

        # 检查关键数据渲染是否使用 textContent / replaceChildren
        has_textcontent = "title.textContent =" in html_content and "reason.textContent =" in html_content
        # 确保不存在 eval()
        has_no_eval = "eval(" not in html_content

        cost = (time.perf_counter() - t0) * 1000
        ok = has_textcontent and has_no_eval
        REPORT.log("SEC01", "前端 DOM 渲染 XSS 注入防护 (textContent)", ok, "", cost)
        self.assertTrue(ok)

    def test_sec02_api_key_not_leaked(self):
        """2. 响应体与数据库中严禁泄露 API Key"""
        t0 = time.perf_counter()
        fake_secret_key = "sk-fake-secret-key-for-leakage-test-12345678"
        with patch.dict(os.environ, {"SILICONFLOW_API_KEY": fake_secret_key}):
            # 创建会话
            c_resp = self.client.post("/api/debates", json={"taste": "辣", "budget": 30, "weather": "晴"})
            did = c_resp.json().get("id")

            # 查询接口
            get_resp = self.client.get(f"/api/debates/{did}")
            list_resp = self.client.get("/api/debates")

            # 查询数据库
            with _db() as conn:
                row = conn.execute("SELECT data FROM debates WHERE id = ?", (did,)).fetchone()
                db_data = row["data"] if row else ""

        cost = (time.perf_counter() - t0) * 1000
        ok = (
            fake_secret_key not in c_resp.text and
            fake_secret_key not in get_resp.text and
            fake_secret_key not in list_resp.text and
            fake_secret_key not in db_data
        )
        REPORT.log("SEC02", "接口响应与数据库 API Key 防泄露隔离", ok, "", cost)
        self.assertTrue(ok)

    def test_sec03_pydantic_length_overflow_defense(self):
        """3. 用户输入超长畸形载荷受 Pydantic 边界防护拦截"""
        t0 = time.perf_counter()
        # 超长字段组合测试
        payloads = [
            {"taste": "x" * 101, "budget": 30, "weather": "晴"},       # taste > 100
            {"taste": "辣", "budget": 501, "weather": "晴"},             # budget > 500
            {"taste": "辣", "budget": 30, "weather": "x" * 51},          # weather > 50
            {"taste": "辣", "budget": 30, "weather": "晴", "restrictions": "x" * 201},  # restrictions > 200
            {"taste": "辣", "budget": 30, "weather": "晴", "note": "x" * 301},          # note > 300
            {"taste": "辣", "budget": 30, "weather": "晴", "spicy_name": "x" * 31},     # spicy_name > 30
            {"taste": "辣", "budget": 30, "weather": "晴", "menu": "x" * 50001},        # menu > 50000
        ]

        all_blocked = True
        for p in payloads:
            r = self.client.post("/api/debates", json=p)
            if r.status_code != 422:
                all_blocked = False
                break

        cost = (time.perf_counter() - t0) * 1000
        REPORT.log("SEC03", "Pydantic 针对超长畸形输入溢出防御 (422拦截)", all_blocked, "", cost)
        self.assertTrue(all_blocked)

    async def test_sec04_sql_injection_defense(self):
        """4. 参数化 SQL 对典型 SQL 注入载荷（UNION/DROP/OR 1=1）进行防御"""
        t0 = time.perf_counter()
        injection_payloads = [
            "'; DROP TABLE favorites; --",
            "' OR '1'='1",
            "1 UNION SELECT 1,2,3,4,5",
            "admin' --",
        ]

        # 准备会话
        c_resp = self.client.post("/api/debates", json={"taste": "辣", "budget": 30, "weather": "晴"})
        did = c_resp.json()["id"]

        injection_safe = True
        for payload in injection_payloads:
            # 注入到收藏菜品名和备注中
            f_resp = self.client.post("/api/favorites", json={
                "debate_id": did,
                "dish": payload,
                "note": payload
            })
            if f_resp.status_code != 200:
                injection_safe = False
                break
            fid = f_resp.json()["id"]

            # 验证 payload 作为字面量安全存储，表结构安然无恙
            with _db() as conn:
                row = conn.execute("SELECT dish FROM favorites WHERE id = ?", (fid,)).fetchone()
                if not row or row["dish"] != payload:
                    injection_safe = False
                    break

        cost = (time.perf_counter() - t0) * 1000
        REPORT.log("SEC04", "SQLite 命名参数化绑定与 SQL 注入免疫", injection_safe, "", cost)
        self.assertTrue(injection_safe)

    def test_sec05_gitignore_security_rules(self):
        """5. 验证 .gitignore 中严格过滤敏感文件与本地数据库"""
        t0 = time.perf_counter()
        gitignore_path = os.path.join(os.path.dirname(__file__), ".gitignore")
        with open(gitignore_path, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f.readlines()]

        has_env = ".env" in lines
        has_sqlite = any("sqlite3" in l for l in lines)
        has_debates_json = "debates.json" in lines
        has_log = any("log" in l for l in lines)
        has_venv = any(".venv" in l for l in lines)

        cost = (time.perf_counter() - t0) * 1000
        ok = has_env and has_sqlite and has_debates_json and has_log and has_venv
        REPORT.log("SEC05", ".gitignore 敏感配置文件与凭据过滤防泄漏", ok, "", cost)
        self.assertTrue(ok)


if __name__ == "__main__":
    suite = unittest.TestLoader().loadTestsFromTestCase(TestSecurity)
    unittest.TextTestRunner(verbosity=0).run(suite)
    success = REPORT.print_summary()
    sys.exit(0 if success else 1)
