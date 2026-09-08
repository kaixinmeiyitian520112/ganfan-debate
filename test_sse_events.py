# test_sse_events.py
"""
SSE 事件顺序与控制测试 (3.6.5)
验证 Server-Sent Events (SSE) 事件发射顺序、事件包结构及控制流
"""

import json
import re
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
    _debate_stream,
)


class SSEReport:
    def __init__(self):
        self.records = []

    def log(self, eid, name, passed, message="", cost_ms=0.0):
        self.records.append({
            "id": eid,
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
        print("          SSE 事件顺序测试执行报告 (3.6.5)")
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


REPORT = SSEReport()


def parse_sse_frames(raw_chunks: list[str]) -> list[tuple[str, dict]]:
    """解析 SSE 格式字符串为 (event_name, data_dict) 序列"""
    frames = []
    full_text = "".join(raw_chunks)
    blocks = [b.strip() for b in full_text.split("\n\n") if b.strip()]
    for block in blocks:
        lines = block.split("\n")
        event = "message"
        data = {}
        for line in lines:
            if line.startswith("event:"):
                event = line.replace("event:", "", 1).strip()
            elif line.startswith("data:"):
                data_str = line.replace("data:", "", 1).strip()
                try:
                    data = json.loads(data_str)
                except Exception:
                    data = {"raw": data_str}
        frames.append((event, data))
    return frames


class TestSSEEvents(unittest.IsolatedAsyncioTestCase):
    async def test_sse01_standard_3_rounds_sequence(self):
        """测试 3 轮辩论标准事件发射序列 (共 13 个事件按严格顺序推进)"""
        t0 = time.perf_counter()
        req = DebateRequest(taste="辣", budget=30, weather="晴", rounds=3)
        session = DebateSession(id="sse_seq_01", request=req)

        # 构造各轮 mock 发言
        counter = 0
        async def mock_chef(s, chef, stance, opponent, persona):
            nonlocal counter
            counter += 1
            cur_round = (counter - 1) // 2 + 1
            return Speech(round=cur_round, chef=chef, recommend=f"菜品{counter}", reason="理由", score=85, stance=stance)

        mock_report = DebateReport(winner="辣子哥", dish="菜品1", score={"辣子哥": 88, "清补凉": 82}, summary="总结", barrage="弹幕")

        chunks = []
        with patch("backend.main._call_chef", side_effect=mock_chef), \
             patch("backend.main._call_judge", new_callable=AsyncMock, return_value=mock_report):
            async for chunk in _debate_stream(session):
                chunks.append(chunk)

        frames = parse_sse_frames(chunks)
        event_names = [f[0] for f in frames]

        # 预期序列：
        # status(DEBATING) -> speech -> speech -> status(r1) -> speech -> speech -> status(r2) -> speech -> speech -> status(r3) -> status(JUDGING) -> report -> status(FINISHED)
        expected_events = [
            "status",
            "speech", "speech", "status",
            "speech", "speech", "status",
            "speech", "speech", "status",
            "status",
            "report",
            "status"
        ]

        cost = (time.perf_counter() - t0) * 1000
        ok = (event_names == expected_events and frames[-2][0] == "report" and frames[-1][1].get("status") == "FINISHED")
        REPORT.log("SSE01", "3 轮标准辩论事件序列严格一致性测试", ok, f"actual={event_names}", cost)
        self.assertTrue(ok)

    async def test_sse02_stopped_event_on_terminate(self):
        """测试用户终止时发射 stopped 事件且无后续 report/finished"""
        t0 = time.perf_counter()
        req = DebateRequest(taste="辣", budget=30, weather="晴", rounds=2)
        session = DebateSession(id="sse_stopped", request=req)

        async def stop_after_first(s, chef, stance, opponent, persona):
            session.status = "TERMINATED"
            return Speech(round=1, chef=chef, recommend="测试菜", reason="测试", score=80, stance=stance)

        chunks = []
        with patch("backend.main._call_chef", side_effect=stop_after_first):
            async for chunk in _debate_stream(session):
                chunks.append(chunk)

        frames = parse_sse_frames(chunks)
        event_names = [f[0] for f in frames]
        cost = (time.perf_counter() - t0) * 1000

        ok = ("stopped" in event_names and "report" not in event_names and event_names[-1] == "stopped")
        REPORT.log("SSE02", "人工终止辩论时发射 stopped 事件校验", ok, "", cost)
        self.assertTrue(ok)

    async def test_sse03_w3c_frame_format(self):
        """测试 SSE 数据包格式符合 W3C 标准 (event: ...\\ndata: ...\\n\\n)"""
        t0 = time.perf_counter()
        from backend.main import _sse
        packet = _sse("speech", {"round": 1, "chef": "辣子哥", "recommend": "麻婆豆腐"})
        cost = (time.perf_counter() - t0) * 1000

        ok = (
            packet.startswith("event: speech\n") and
            "data: {" in packet and
            "\"recommend\": \"麻婆豆腐\"" in packet and
            packet.endswith("\n\n")
        )
        REPORT.log("SSE03", "SSE 帧打包格式 (W3C 协议合规性)", ok, "", cost)
        self.assertTrue(ok)


if __name__ == "__main__":
    suite = unittest.TestLoader().loadTestsFromTestCase(TestSSEEvents)
    unittest.TextTestRunner(verbosity=0).run(suite)
    success = REPORT.print_summary()
    sys.exit(0 if success else 1)
