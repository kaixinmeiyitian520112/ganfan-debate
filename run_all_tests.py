# run_all_tests.py
"""
干饭辩论赛 - 软件工程全维度测试主入口
一键运行《项目开发说明文档》3.6 节中所有大类的独立测试文件
"""

import subprocess
import sys
import time

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

TEST_MODULES = [
    ("test_blackbox_interfaces.py", "3.6.3 接口黑盒测试表 (T01 - T13)"),
    ("test_whitebox_stream.py",     "3.6.4 白盒测试设计 (语句/分支/基本路径 P1-P6)"),
    ("test_sse_events.py",          "3.6.5 SSE 事件顺序与控制流测试"),
    ("test_database.py",            "3.6.6 SQLite 数据库测试 (1-7 项)"),
    ("test_agent_config.py",        "3.6.7 Agent 人设与配置测试 (1-6 项)"),
    ("test_exceptions.py",          "3.6.8 系统异常与容错测试 (1-9 项)"),
    ("test_security.py",            "3.6.9 系统安全与注入防御测试 (1-5 项)"),
    ("scenario_tests_b01_b08.py",   "3.6.3(3) 场景测试业务全覆盖 (B01 - B08)"),
]

def main():
    print("\n" + "=" * 90)
    print("      干饭辩论赛 - 软件工程测试套件 (全大类独立执行启动)")
    print("=" * 90 + "\n")

    results = []
    start_all = time.perf_counter()

    for script, desc in TEST_MODULES:
        print(f"▶ 正在执行 [{script}] - {desc} ...")
        t0 = time.perf_counter()
        proc = subprocess.run([sys.executable, script], capture_output=True, text=True, encoding="utf-8", errors="replace")
        cost = (time.perf_counter() - t0) * 1000

        passed = (proc.returncode == 0)
        results.append({
            "script": script,
            "desc": desc,
            "passed": passed,
            "cost": round(cost, 2),
            "stdout": proc.stdout,
            "stderr": proc.stderr
        })
        status_tag = "[PASS]" if passed else "[FAIL]"
        print(f"  └─ 结果: {status_tag} (耗时: {cost:.1f}ms)")
        if not passed:
            print("     错误详情:\n" + proc.stdout + "\n" + proc.stderr)

    total_time = (time.perf_counter() - start_all) * 1000
    all_passed = all(r["passed"] for r in results)

    print("\n" + "=" * 90)
    print(f"       全维度测试执行总览汇总表 (共 {len(TEST_MODULES)} 个独立测试大类)")
    print("=" * 90)
    print(f"{'测试脚本文件':<30}{'大类描述':<38}{'耗时(ms)':<10}{'状态'}")
    print("-" * 90)
    for r in results:
        status_tag = " [PASS] " if r["passed"] else "![FAIL]!"
        print(f"{r['script']:<30}{r['desc']:<38}{r['cost']:<10}{status_tag}")
    print("=" * 90)
    print(f"总体结果: {'全部测试大类通过 (100% PASS)' if all_passed else '存在失败大类'}")
    print(f"总执行耗时: {total_time:.2f} ms\n")

    sys.exit(0 if all_passed else 1)

if __name__ == "__main__":
    main()
