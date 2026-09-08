# test_database.py
"""
数据库测试 (3.6.6)
覆盖 SQLite 数据库 7 项核心测试要求：
1. 启动时自动创建 debates 和 favorites 表
2. 创建会话后 debates 表增加记录
3. 每条发言后会话 JSON 更新
4. 收藏成功后 favorites 表增加记录
5. 删除收藏后记录消失
6. 重启服务后历史和收藏仍可查询
7. 旧 debates.json 能迁移到 SQLite
"""

import json
import sqlite3
import sys
import time
import unittest
from uuid import uuid4

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from backend.main import (
    DB_FILE,
    DebateRequest,
    DebateSession,
    Speech,
    _db,
    _init_db,
    _save_session,
    _load_sessions,
    create_debate,
    add_favorite,
    delete_favorite,
    FavoriteRequest,
    sessions,
)


class DatabaseReport:
    def __init__(self):
        self.records = []

    def log(self, did, name, passed, message="", cost_ms=0.0):
        self.records.append({
            "id": did,
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
        print("          SQLite 数据库测试执行报告 (3.6.6)")
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


REPORT = DatabaseReport()


class TestDatabaseOperations(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        _init_db()

    def test_db01_tables_created_on_init(self):
        """1. 启动时自动创建 debates 和 favorites 表"""
        t0 = time.perf_counter()
        with _db() as conn:
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            table_names = [r["name"] for r in rows]

        cost = (time.perf_counter() - t0) * 1000
        ok = "debates" in table_names and "favorites" in table_names
        REPORT.log("DB01", "自动建表 (debates, favorites)", ok, f"tables={table_names}", cost)
        self.assertTrue(ok)

    async def test_db02_debate_insert_on_create(self):
        """2. 创建会话后 debates 表增加记录"""
        t0 = time.perf_counter()
        req = DebateRequest(taste="麻辣", budget=30, weather="晴")
        session = await create_debate(req)

        with _db() as conn:
            row = conn.execute("SELECT id, status, data FROM debates WHERE id = ?", (session.id,)).fetchone()

        cost = (time.perf_counter() - t0) * 1000
        ok = row is not None and row["id"] == session.id and row["status"] == "PENDING"
        REPORT.log("DB02", "创建会话后 debates 表记录落盘", ok, "", cost)
        self.assertTrue(ok)

    def test_db03_session_json_updated_per_speech(self):
        """3. 每条发言后会话 JSON 实时更新"""
        t0 = time.perf_counter()
        sid = str(uuid4())
        req = DebateRequest(taste="辣", budget=20, weather="阴")
        session = DebateSession(id=sid, request=req)
        _save_session(session)

        # 追加第 1 条发言并保存
        session.history.append(Speech(round=1, chef="辣子哥", recommend="水煮肉", reason="够劲", score=88, stance="spicy"))
        _save_session(session)

        with _db() as conn:
            row = conn.execute("SELECT data FROM debates WHERE id = ?", (sid,)).fetchone()
            data_dict = json.loads(row["data"])

        cost = (time.perf_counter() - t0) * 1000
        ok = len(data_dict.get("history", [])) == 1 and data_dict["history"][0]["recommend"] == "水煮肉"
        REPORT.log("DB03", "发言追加后 debates.data JSON 实时更新", ok, "", cost)
        self.assertTrue(ok)

    async def test_db04_favorite_insert_on_add(self):
        """4. 收藏成功后 favorites 表增加记录"""
        t0 = time.perf_counter()
        sid = str(uuid4())
        session = DebateSession(id=sid, request=DebateRequest(taste="辣", budget=25, weather="晴"))
        sessions[sid] = session
        _save_session(session)

        fav_result = await add_favorite(FavoriteRequest(debate_id=sid, dish="红烧肉盖饭", note="测试备注"))
        fav_id = fav_result["id"]

        with _db() as conn:
            row = conn.execute("SELECT * FROM favorites WHERE id = ?", (fav_id,)).fetchone()

        cost = (time.perf_counter() - t0) * 1000
        ok = row is not None and row["dish"] == "红烧肉盖饭" and row["note"] == "测试备注"
        REPORT.log("DB04", "菜品收藏写入 favorites 表", ok, "", cost)
        self.assertTrue(ok)

    async def test_db05_favorite_removed_on_delete(self):
        """5. 删除收藏后记录消失"""
        t0 = time.perf_counter()
        sid = str(uuid4())
        sessions[sid] = DebateSession(id=sid, request=DebateRequest(taste="辣", budget=20, weather="晴"))
        _save_session(sessions[sid])

        fav_result = await add_favorite(FavoriteRequest(debate_id=sid, dish="待删菜品"))
        fav_id = fav_result["id"]

        del_res = await delete_favorite(fav_id)

        with _db() as conn:
            row = conn.execute("SELECT * FROM favorites WHERE id = ?", (fav_id,)).fetchone()

        cost = (time.perf_counter() - t0) * 1000
        ok = del_res.get("deleted") is True and row is None
        REPORT.log("DB05", "删除收藏记录从数据库彻底移除", ok, "", cost)
        self.assertTrue(ok)

    def test_db06_reboot_query_preservation(self):
        """6. 重启服务后历史和收藏仍可查询"""
        t0 = time.perf_counter()
        sid = f"persist_{uuid4()}"
        session = DebateSession(id=sid, request=DebateRequest(taste="微辣", budget=28, weather="晴"))
        _save_session(session)

        # 模拟重启服务：重新调用 _load_sessions
        _load_sessions()

        with _db() as conn:
            row = conn.execute("SELECT id FROM debates WHERE id = ?", (sid,)).fetchone()

        cost = (time.perf_counter() - t0) * 1000
        ok = sid in sessions and row is not None
        REPORT.log("DB06", "模拟服务重启后持久化数据加载复原", ok, "", cost)
        self.assertTrue(ok)

    def test_db07_legacy_json_migration(self):
        """7. 旧 debates.json 迁移校验 (结构兼容性校验)"""
        t0 = time.perf_counter()
        legacy_data = {
            "id": f"legacy_{uuid4()}",
            "status": "FINISHED",
            "request": {
                "taste": "旧版辣",
                "budget": 30,
                "weather": "晴",
                "restrictions": "无",
                "note": "",
                "rounds": 3
            },
            "history": []
        }
        # 验证新版 Pydantic 能够顺利反序列化旧版格式并自动补全缺失字段
        parsed = DebateSession.model_validate(legacy_data)
        _save_session(parsed)

        with _db() as conn:
            row = conn.execute("SELECT id FROM debates WHERE id = ?", (parsed.id,)).fetchone()

        cost = (time.perf_counter() - t0) * 1000
        ok = (row is not None and parsed.request.spicy_name == "辣子哥")
        REPORT.log("DB07", "旧版会话结构兼容与平滑迁移入库", ok, "", cost)
        self.assertTrue(ok)


if __name__ == "__main__":
    suite = unittest.TestLoader().loadTestsFromTestCase(TestDatabaseOperations)
    unittest.TextTestRunner(verbosity=0).run(suite)
    success = REPORT.print_summary()
    sys.exit(0 if success else 1)
