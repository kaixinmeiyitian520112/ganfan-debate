# test_exceptions.py
"""
异常与容错测试 (3.6.8)
覆盖 API Key 缺失、超时重试、非法 JSON、裁判兜底、并发锁拦截、404 与终止保护
"""

import asyncio
import os
import sys
import time
import unittest
from unittest.mock import AsyncMock, patch

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from fastapi.testclient import TestClient
from fastapi import HTTPException
from backend.main import (
    app,
    DebateRequest,
    DebateSession,
    DebateReport,
    Speech,
    _call_chef,
    _call_judge,
    _fallback_report,
    _fallback_speech,
    _debate_stream,
    stream_debate,
    stream_locks,
    sessions,
)


class ExceptionReport:
    def __init__(self):
        self.records = []

    def log(self, xid, name, passed, message="", cost_ms=0.0):
        self.records.append({
            "id": xid,
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
        print("          系统异常与容错测试执行报告 (3.6.8)")
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


REPORT = ExceptionReport()


class TestExceptions(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    async def test_exc01_api_key_missing(self):
        """1. API Key 缺失时抛出明确配置错误"""
        t0 = time.perf_counter()
        req = DebateRequest(taste="辣", budget=30, weather="晴")
        session = DebateSession(id="test_no_key", request=req)

        with patch.dict(os.environ, {"SILICONFLOW_API_KEY": ""}):
            with self.assertRaises(RuntimeError) as ctx:
                await _call_chef(session, "辣子哥", "spicy", "清补凉", "人设")

        cost = (time.perf_counter() - t0) * 1000
        ok = "未配置 SILICONFLOW_API_KEY" in str(ctx.exception)
        REPORT.log("EXC01", "API Key 缺失明确配置提示校验", ok, "", cost)
        self.assertTrue(ok)

    async def test_exc02_timeout_retry_and_save(self):
        """2. 模型超时能够触发重试机制并保存已有进度"""
        t0 = time.perf_counter()
        req = DebateRequest(taste="辣", budget=30, weather="晴", rounds=1)
        session = DebateSession(id="test_timeout", request=req)

        attempts = 0
        async def mock_timeout_chef(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts < 2:
                raise RuntimeError("Request timeout 504")
            return Speech(round=1, chef="辣子哥", recommend="水煮肉", reason="够辣", score=85, stance="spicy")

        with patch("backend.main._call_chef", side_effect=mock_timeout_chef), \
             patch("backend.main._call_judge", new_callable=AsyncMock), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            async for chunk in _debate_stream(session):
                if "event: speech" in chunk:
                    break

        cost = (time.perf_counter() - t0) * 1000
        ok = (attempts >= 2 and len(session.history) >= 1)
        REPORT.log("EXC02", "超时自动指数退避重试并持久化进度", ok, "", cost)
        self.assertTrue(ok)

    def test_exc03_invalid_json_fallback(self):
        """3. 模型返回非法 JSON 时能够触发兜底逻辑"""
        t0 = time.perf_counter()
        req = DebateRequest(taste="辣", budget=30, weather="晴", menu="菜品：麻婆豆腐")
        session = DebateSession(id="test_bad_json", request=req)
        # 模拟非法 JSON 报错触发兜底函数
        speech = _fallback_speech(session, "辣子哥", "spicy", ValueError("Unterminated string"))
        cost = (time.perf_counter() - t0) * 1000

        ok = (speech.recommend == "麻婆豆腐" and speech.score == 70)
        REPORT.log("EXC03", "非法 JSON 解析异常降级至本地保底", ok, "", cost)
        self.assertTrue(ok)

    def test_exc04_judge_failure_fallback_report(self):
        """4. 裁判失败时自动使用本地均分生成有效战报"""
        t0 = time.perf_counter()
        req = DebateRequest(taste="辣", budget=30, weather="晴")
        session = DebateSession(
            id="test_judge_fail",
            request=req,
            history=[
                Speech(round=1, chef="辣子哥", recommend="回锅肉", reason="香", score=90, stance="spicy"),
                Speech(round=1, chef="清补凉", recommend="荷包鸡", reason="鲜", score=80, stance="healthy"),
            ]
        )
        report = _fallback_report(session)
        cost = (time.perf_counter() - t0) * 1000

        ok = (report.winner == "辣子哥" and report.dish == "回锅肉" and report.score["辣子哥"] == 90)
        REPORT.log("EXC04", "裁判异常时本地算术决胜战报保底", ok, "", cost)
        self.assertTrue(ok)

    async def test_exc05_sse_disconnect_resume(self):
        """5. SSE 中途中断后，再次执行从 history.length 续传"""
        t0 = time.perf_counter()
        req = DebateRequest(taste="辣", budget=30, weather="晴", rounds=2)
        session = DebateSession(
            id="test_resume",
            request=req,
            history=[
                Speech(round=1, chef="辣子哥", recommend="菜品1", reason="理由1", score=80, stance="spicy"),
                Speech(round=1, chef="清补凉", recommend="菜品2", reason="理由2", score=80, stance="healthy"),
            ]
        )

        called_turns = []
        async def mock_chef(s, chef, stance, opponent, persona):
            called_turns.append(chef)
            return Speech(round=2, chef=chef, recommend="菜品3", reason="理由3", score=80, stance=stance)

        mock_report = DebateReport(
            winner="辣子哥",
            dish="菜品3",
            score={"辣子哥": 80, "清补凉": 80},
            summary="平分秋色",
            barrage="赞"
        )

        with patch("backend.main._call_chef", side_effect=mock_chef), \
             patch("backend.main._call_judge", new_callable=AsyncMock, return_value=mock_report):
            async for _ in _debate_stream(session):
                pass

        cost = (time.perf_counter() - t0) * 1000
        # 总共 2 轮 = 4 条发言，已有 2 条，因此 _call_chef 应该只被调用 2 次续传
        ok = (len(called_turns) == 2 and len(session.history) == 4)
        REPORT.log("EXC05", "中断刷新后精准断点续传（不重复生成）", ok, f"called={len(called_turns)}", cost)
        self.assertTrue(ok)

    async def test_exc06_lock_conflict_409(self):
        """6. 重复并发打开流被 asyncio.Lock 拦截返回 409"""
        t0 = time.perf_counter()
        sid = "test_exc_lock"
        session = DebateSession(id=sid, request=DebateRequest(taste="辣", budget=30, weather="晴"))
        sessions[sid] = session

        lock = stream_locks.setdefault(sid, asyncio.Lock())
        await lock.acquire()

        try:
            await stream_debate(sid)
            got_409 = False
        except HTTPException as e:
            got_409 = (e.status_code == 409)
        finally:
            lock.release()

        cost = (time.perf_counter() - t0) * 1000
        REPORT.log("EXC06", "同一会话并发竞争时 409 拦截机制", got_409, "", cost)
        self.assertTrue(got_409)

    def test_exc07_delete_nonexistent_favorite_404(self):
        """7. 删除不存在的收藏记录返回 404"""
        t0 = time.perf_counter()
        resp = self.client.delete("/api/favorites/99999999")
        cost = (time.perf_counter() - t0) * 1000
        ok = (resp.status_code == 404 and "收藏不存在" in resp.json()["detail"])
        REPORT.log("EXC07", "删除不存在收藏实体 404 响应", ok, "", cost)
        self.assertTrue(ok)

    def test_exc08_get_nonexistent_debate_404(self):
        """8. 查询不存在的会话返回 404"""
        t0 = time.perf_counter()
        resp = self.client.get("/api/debates/non-existent-session-id-1234")
        cost = (time.perf_counter() - t0) * 1000
        ok = (resp.status_code == 404 and "不存在或已过期" in resp.json()["detail"])
        REPORT.log("EXC08", "查询不存在会话实体 404 响应", ok, "", cost)
        self.assertTrue(ok)

    async def test_exc09_stop_finished_debate_status(self):
        """9. 对已完成状态的辩论再次发起流式请求返回 409 拒绝继续生成"""
        t0 = time.perf_counter()
        sid = "test_finished_409"
        session = DebateSession(id=sid, status="FINISHED", request=DebateRequest(taste="辣", budget=30, weather="晴"))
        sessions[sid] = session

        cost = 0.0
        try:
            await stream_debate(sid)
            finished_rejected = False
        except HTTPException as e:
            finished_rejected = (e.status_code == 409 and "已结束" in e.detail)
        finally:
            cost = (time.perf_counter() - t0) * 1000

        REPORT.log("EXC09", "已完赛会话再次请求流 409 保护拦截", finished_rejected, "", cost)
        self.assertTrue(finished_rejected)


if __name__ == "__main__":
    suite = unittest.TestLoader().loadTestsFromTestCase(TestExceptions)
    unittest.TextTestRunner(verbosity=0).run(suite)
    success = REPORT.print_summary()
    sys.exit(0 if success else 1)
