# test_whitebox_stream.py
"""
白盒测试设计 (3.6.4)
以 _debate_stream 为核心，覆盖语句覆盖、分支覆盖与基本路径测试 (P1 - P6)
"""

import asyncio
import sys
import time
import unittest
from unittest.mock import AsyncMock, patch

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from fastapi import HTTPException
from backend.main import (
    DebateRequest,
    DebateSession,
    Speech,
    DebateReport,
    _debate_stream,
    stream_debate,
    stream_locks,
)


class WhiteboxReport:
    def __init__(self):
        self.records = []

    def log(self, pid, name, passed, message="", cost_ms=0.0):
        self.records.append({
            "id": pid,
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
        print("          白盒测试执行报告 (语句/分支/基本路径 P1 - P6)")
        print("=" * 90)
        print(f"{'编号':<6}{'路径/分支测试':<38}{'耗时(ms)':<10}{'状态'}")
        print("-" * 90)
        for r in self.records:
            status = " [PASS] " if r["passed"] else "![FAIL]!"
            print(f"{r['id']:<6}{r['name']:<38}{r['cost_ms']:<10}{status}")
            if not r["passed"] and r["message"]:
                print(f"       -> 错误原因: {r['message']}")
        print("=" * 90)
        print(f"总计: {total} 个用例 | 通过: {passed} | 失败: {failed} | 成功率: {passed/max(1, total)*100:.1f}%\n")
        return failed == 0


REPORT = WhiteboxReport()


class TestWhiteboxStream(unittest.IsolatedAsyncioTestCase):
    async def test_p1_normal_flow_to_finished(self):
        """P1: 创建会话 -> 正常生成全部 speech -> 裁判成功 -> FINISHED"""
        t0 = time.perf_counter()
        req = DebateRequest(taste="香辣", budget=30, weather="晴", rounds=1)
        session = DebateSession(id="wb_p1", request=req)

        mock_speech = Speech(round=1, chef="辣子哥", recommend="辣子鸡", reason="香辣酥脆", score=90, stance="spicy")
        mock_report = DebateReport(winner="辣子哥", dish="辣子鸡", score={"辣子哥": 90, "清补凉": 80}, summary="胜出", barrage="点赞")

        events = []
        with patch("backend.main._call_chef", new_callable=AsyncMock, return_value=mock_speech), \
             patch("backend.main._call_judge", new_callable=AsyncMock, return_value=mock_report):
            async for chunk in _debate_stream(session):
                events.append(chunk)

        cost = (time.perf_counter() - t0) * 1000
        ok = (
            session.status == "FINISHED" and
            session.report is not None and
            len(session.history) == 2 and
            any("event: report" in e for e in events) and
            any('"status": "FINISHED"' in e for e in events)
        )
        REPORT.log("P1", "正常生成全部发言并裁判完成 -> FINISHED", ok, "", cost)
        self.assertTrue(ok)

    async def test_p2_chef_retry_success(self):
        """P2: 创建会话 -> Agent 第一次失败 -> 重试成功 -> 继续生成"""
        t0 = time.perf_counter()
        req = DebateRequest(taste="辣", budget=30, weather="晴", rounds=1)
        session = DebateSession(id="wb_p2", request=req)

        mock_speech = Speech(round=1, chef="清补凉", recommend="清蒸鱼", reason="清淡鲜美", score=85, stance="healthy")
        mock_report = DebateReport(winner="清补凉", dish="清蒸鱼", score={"清补凉": 85, "辣子哥": 80}, summary="胜出", barrage="赞")

        # 模拟第 1 次调用失败，第 2 次重试成功
        call_count = 0
        async def flaky_chef(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("网络偶发波动 504")
            return mock_speech

        with patch("backend.main._call_chef", side_effect=flaky_chef), \
             patch("backend.main._call_judge", new_callable=AsyncMock, return_value=mock_report), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            async for _ in _debate_stream(session):
                pass

        cost = (time.perf_counter() - t0) * 1000
        ok = (session.status == "FINISHED" and len(session.history) == 2 and call_count >= 2)
        REPORT.log("P2", "Agent 偶发异常重试成功并继续生成", ok, "", cost)
        self.assertTrue(ok)

    async def test_p3_chef_consecutive_failure_fallback(self):
        """P3: 创建会话 -> Agent 连续失败 -> 兜底 speech -> 继续后续轮次"""
        t0 = time.perf_counter()
        req = DebateRequest(taste="辣", budget=30, weather="晴", rounds=1, menu="菜品：麻婆豆腐；价格：18")
        session = DebateSession(id="wb_p3", request=req)

        mock_report = DebateReport(winner="辣子哥", dish="麻婆豆腐", score={"辣子哥": 70, "清补凉": 70}, summary="胜出", barrage="赞")

        # 模拟厨师连续调用全部失败
        async def failing_chef(*args, **kwargs):
            raise RuntimeError("服务彻底不可用")

        with patch("backend.main._call_chef", side_effect=failing_chef), \
             patch("backend.main._call_judge", new_callable=AsyncMock, return_value=mock_report), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            async for _ in _debate_stream(session):
                pass

        cost = (time.perf_counter() - t0) * 1000
        ok = (
            session.status == "FINISHED" and
            len(session.history) == 2 and
            session.history[0].recommend == "麻婆豆腐" and
            session.history[0].score == 70  # 兜底分数为 70
        )
        REPORT.log("P3", "Agent 连续三次失败触发本地保底发言", ok, "", cost)
        self.assertTrue(ok)

    async def test_p4_judge_consecutive_failure_fallback(self):
        """P4: 完成发言 -> 裁判三次失败 -> _fallback_report -> FINISHED"""
        t0 = time.perf_counter()
        req = DebateRequest(taste="辣", budget=30, weather="晴", rounds=1)
        session = DebateSession(id="wb_p4", request=req)

        mock_speech = Speech(round=1, chef="辣子哥", recommend="麻婆豆腐", reason="好吃", score=90, stance="spicy")

        # 模拟裁判连续调用全部失败
        async def failing_judge(*args, **kwargs):
            raise RuntimeError("裁判服务不可用")

        with patch("backend.main._call_chef", new_callable=AsyncMock, return_value=mock_speech), \
             patch("backend.main._call_judge", side_effect=failing_judge), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            async for _ in _debate_stream(session):
                pass

        cost = (time.perf_counter() - t0) * 1000
        ok = (
            session.status == "FINISHED" and
            session.report is not None and
            session.report.barrage == "裁判临时离席，先按场上比分判定！"
        )
        REPORT.log("P4", "裁判连续三次失败触发本地均分兜底战报", ok, "", cost)
        self.assertTrue(ok)

    async def test_p5_user_terminated_midway(self):
        """P5: 生成期间终止 -> TERMINATED -> stopped -> 流结束"""
        t0 = time.perf_counter()
        req = DebateRequest(taste="辣", budget=30, weather="晴", rounds=3)
        session = DebateSession(id="wb_p5", request=req)

        # 模拟在第 1 轮发言后用户触发终止
        async def terminating_chef(*args, **kwargs):
            session.status = "TERMINATED"
            return Speech(round=1, chef="辣子哥", recommend="辣子鸡", reason="够辣", score=90, stance="spicy")

        events = []
        with patch("backend.main._call_chef", side_effect=terminating_chef):
            async for chunk in _debate_stream(session):
                events.append(chunk)

        cost = (time.perf_counter() - t0) * 1000
        ok = (
            session.status == "TERMINATED" and
            any("event: stopped" in e for e in events) and
            not any("event: report" in e for e in events)
        )
        REPORT.log("P5", "运行期间接收终止信号安全退出 -> stopped", ok, "", cost)
        self.assertTrue(ok)

    async def test_p6_lock_conflict_prevention(self):
        """P6: 重复连接 -> asyncio.Lock 拦截并返回 409"""
        t0 = time.perf_counter()
        req = DebateRequest(taste="辣", budget=30, weather="晴", rounds=2)
        session = DebateSession(id="wb_p6", request=req)
        from backend.main import sessions
        sessions[session.id] = session

        lock = stream_locks.setdefault(session.id, asyncio.Lock())
        await lock.acquire()  # 手动加锁模拟已有活跃流

        cost = 0.0
        try:
            await stream_debate(session.id)
            conflict_caught = False
        except HTTPException as e:
            conflict_caught = (e.status_code == 409)
        finally:
            lock.release()
            cost = (time.perf_counter() - t0) * 1000

        REPORT.log("P6", "并发双连接竞争检测 -> asyncio.Lock 拦截 409", conflict_caught, "", cost)
        self.assertTrue(conflict_caught)


if __name__ == "__main__":
    suite = unittest.TestLoader().loadTestsFromTestCase(TestWhiteboxStream)
    unittest.TextTestRunner(verbosity=0).run(suite)
    success = REPORT.print_summary()
    sys.exit(0 if success else 1)
