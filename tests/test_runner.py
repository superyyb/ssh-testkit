"""
Unit tests for TestRunner — concurrent execution, on_result callback, retry logic.
Uses a mock SSH client so no real SSH connection is needed.
"""
import pytest
from unittest.mock import MagicMock
from framework.test_runner import TestRunner


def make_ssh(stdout="", stderr="", exit_code=0):
    """Return a mock SSH client whose run_command returns the given output."""
    client = MagicMock()
    client.run_command.return_value = {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
    }
    return client


# ── Basic execution ────────────────────────────────────────────────────────────

class TestRunAll:

    def test_runs_all_tests_sequentially(self):
        ssh = make_ssh(stdout="load average", exit_code=0)
        tests = [
            {"name": "test1", "command": "uptime", "pass_regex": "load average"},
            {"name": "test2", "command": "uptime", "pass_regex": "load average"},
        ]
        runner = TestRunner(ssh, tests)
        results = runner.run_all(max_workers=1)
        assert len(results) == 2
        assert all(r["status"] == "PASS" for r in results)

    def test_runs_all_tests_concurrently(self):
        ssh = make_ssh(stdout="load average", exit_code=0)
        tests = [
            {"name": f"test{i}", "command": "uptime", "pass_regex": "load average"}
            for i in range(5)
        ]
        runner = TestRunner(ssh, tests)
        results = runner.run_all(max_workers=4)
        assert len(results) == 5
        assert all(r["status"] == "PASS" for r in results)

    def test_run_single_by_name(self):
        ssh = make_ssh(stdout="LISTEN", exit_code=0)
        tests = [
            {"name": "check port", "command": "ss", "pass_regex": "LISTEN"},
            {"name": "other",      "command": "ls",  "pass_regex": "LISTEN"},
        ]
        runner = TestRunner(ssh, tests)
        result = runner.run_single("check port")
        assert result["name"] == "check port"
        assert result["status"] == "PASS"

    def test_run_single_raises_on_unknown_name(self):
        ssh = make_ssh()
        runner = TestRunner(ssh, [{"name": "test1", "command": "ls"}])
        with pytest.raises(ValueError, match="not found"):
            runner.run_single("nonexistent")


# ── on_result callback ─────────────────────────────────────────────────────────

class TestOnResultCallback:

    def test_callback_called_for_every_result(self):
        ssh = make_ssh(stdout="ok", exit_code=0)
        tests = [
            {"name": f"test{i}", "command": "ls", "pass_regex": "ok"}
            for i in range(3)
        ]
        called = []
        runner = TestRunner(ssh, tests)
        runner.run_all(max_workers=1, on_result=lambda r: called.append(r["name"]))
        assert len(called) == 3

    def test_callback_receives_correct_status(self):
        ssh = make_ssh(stdout="ERROR", exit_code=1)
        tests = [{"name": "fail_test", "command": "ls", "fail_regex": "ERROR"}]
        statuses = []
        runner = TestRunner(ssh, tests)
        runner.run_all(on_result=lambda r: statuses.append(r["status"]))
        assert statuses == ["FAIL"]

    def test_callback_called_concurrently(self):
        ssh = make_ssh(stdout="ok", exit_code=0)
        tests = [
            {"name": f"test{i}", "command": "ls", "pass_regex": "ok"}
            for i in range(4)
        ]
        called = []
        runner = TestRunner(ssh, tests)
        runner.run_all(max_workers=4, on_result=lambda r: called.append(r["name"]))
        assert len(called) == 4


# ── Retry logic ────────────────────────────────────────────────────────────────

class TestRetryLogic:

    def test_retries_on_failure_then_passes(self):
        """First call fails, second call passes — should report FLAKY with 2 attempts."""
        ssh = MagicMock()
        ssh.run_command.side_effect = [
            {"stdout": "",   "stderr": "", "exit_code": 1},  # attempt 1: FAIL
            {"stdout": "ok", "stderr": "", "exit_code": 0},  # attempt 2: PASS
        ]
        tests = [{"name": "flaky", "command": "ls", "pass_regex": "ok", "retries": 1}]
        runner = TestRunner(ssh, tests)
        results = runner.run_all()
        assert results[0]["status"] == "FLAKY"
        assert results[0]["attempts"] == 2

    def test_fails_after_all_retries_exhausted(self):
        ssh = make_ssh(stdout="", exit_code=1)
        tests = [{"name": "always_fail", "command": "ls", "pass_regex": "ok", "retries": 2}]
        runner = TestRunner(ssh, tests)
        results = runner.run_all()
        assert results[0]["status"] == "FAIL"
        assert results[0]["attempts"] == 3  # 1 original + 2 retries

    def test_no_retry_on_pass(self):
        ssh = make_ssh(stdout="ok", exit_code=0)
        tests = [{"name": "pass_first", "command": "ls", "pass_regex": "ok", "retries": 3}]
        runner = TestRunner(ssh, tests)
        results = runner.run_all()
        assert results[0]["status"] == "PASS"
        assert results[0]["attempts"] == 1  # should not retry after PASS
