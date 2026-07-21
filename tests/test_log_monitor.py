"""
Unit tests for LogMonitor — pattern matching, alert callback, seen-line dedup.
Uses a mock SSH client so no real SSH connection is needed.
"""
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock
from framework.log_monitor import LogMonitor

FIXTURES = Path(__file__).parent / "fixtures"

# fail_patterns from test_plan.yaml — used in fixture tests
ALL_PATTERNS = [
    "ERROR",
    "FATAL",
    "Exception",
    r"Traceback \(most recent call last\)",
    r"took [1-9]\d{3,} ms",
]


def fixture_monitor(fixture_name, patterns, callback, interval=0.05):
    """Build a LogMonitor backed by a device fixture file."""
    ssh = MagicMock()
    ssh.run_command.return_value = {"stdout": (FIXTURES / fixture_name).read_text()}
    return LogMonitor(
        ssh_client=ssh,
        log_path="/fake/app.log",
        fail_patterns=patterns,
        alert_callback=lambda line, pattern: callback(line),
        interval=interval,
    )


def make_monitor(lines, patterns, callback, interval=0.05):
    """Helper: build a LogMonitor backed by a mock SSH client."""
    ssh = MagicMock()
    ssh.run_command.return_value = {"stdout": "\n".join(lines)}
    return LogMonitor(
        ssh_client=ssh,
        log_path="/fake/app.log",
        fail_patterns=patterns,
        alert_callback=lambda line, pattern: callback(line),
        interval=interval,
    )


# ── Alert triggering ───────────────────────────────────────────────────────────

class TestAlertTriggering:

    def test_triggers_on_matching_pattern(self):
        alerts = []
        monitor = make_monitor(
            lines=["INFO: all good", "ERROR: disk full"],
            patterns=["ERROR"],
            callback=alerts.append,
        )
        monitor.start()
        time.sleep(0.2)
        monitor.stop()
        assert len(alerts) == 1
        assert "ERROR" in alerts[0]

    def test_no_alert_when_no_match(self):
        alerts = []
        monitor = make_monitor(
            lines=["INFO: startup complete", "INFO: request received"],
            patterns=["ERROR", "FATAL"],
            callback=alerts.append,
        )
        monitor.start()
        time.sleep(0.2)
        monitor.stop()
        assert alerts == []

    def test_triggers_on_fatal_pattern(self):
        alerts = []
        monitor = make_monitor(
            lines=["FATAL: out of memory"],
            patterns=["ERROR", "FATAL"],
            callback=alerts.append,
        )
        monitor.start()
        time.sleep(0.2)
        monitor.stop()
        assert len(alerts) == 1

    def test_case_insensitive_matching(self):
        alerts = []
        monitor = make_monitor(
            lines=["error: something went wrong"],
            patterns=["ERROR"],
            callback=alerts.append,
        )
        monitor.start()
        time.sleep(0.2)
        monitor.stop()
        assert len(alerts) == 1


# ── Deduplication ─────────────────────────────────────────────────────────────

class TestDeduplication:

    def test_same_line_not_alerted_twice(self):
        """Monitor polls multiple times but same line should only alert once."""
        alerts = []
        ssh = MagicMock()
        ssh.run_command.return_value = {"stdout": "ERROR: disk full"}
        monitor = LogMonitor(
            ssh_client=ssh,
            log_path="/fake/app.log",
            fail_patterns=["ERROR"],
            alert_callback=lambda line, pattern: alerts.append(line),
            interval=0.05,
        )
        monitor.start()
        time.sleep(0.3)  # let it poll multiple times
        monitor.stop()
        assert len(alerts) == 1  # only alerted once despite multiple polls


# ── Start / Stop ───────────────────────────────────────────────────────────────

class TestStartStop:

    def test_stop_terminates_thread(self):
        alerts = []
        monitor = make_monitor(
            lines=["INFO: ok"],
            patterns=["ERROR"],
            callback=alerts.append,
        )
        monitor.start()
        assert monitor._thread.is_alive()
        monitor.stop()
        assert not monitor._thread.is_alive()

    def test_no_alerts_after_stop(self):
        alerts = []
        ssh = MagicMock()
        ssh.run_command.return_value = {"stdout": "ERROR: something bad"}
        monitor = LogMonitor(
            ssh_client=ssh,
            log_path="/fake/app.log",
            fail_patterns=["ERROR"],
            alert_callback=lambda line, pattern: alerts.append(line),
            interval=0.05,
        )
        monitor.start()
        time.sleep(0.1)
        monitor.stop()
        count_at_stop = len(alerts)
        time.sleep(0.2)  # wait after stop
        assert len(alerts) == count_at_stop  # no new alerts after stop


# ── Realistic fixture tests ────────────────────────────────────────────────────

class TestRealisticFixtures:
    """Feed real device log fixtures to LogMonitor — verifies pattern matching
    works against multi-line production-format logs, not just single-line stubs."""

    def test_no_alert_on_healthy_log(self):
        """device_01: all INFO lines — none of the production fail_patterns fire."""
        alerts = []
        monitor = fixture_monitor("device_01_healthy_operation.log", ALL_PATTERNS, alerts.append)
        monitor.start()
        time.sleep(0.2)
        monitor.stop()
        assert alerts == []

    def test_detects_exception_buried_in_normal_traffic(self):
        """device_02: ERROR and Traceback appear mid-log, surrounded by normal INFO lines."""
        alerts = []
        monitor = fixture_monitor(
            "device_02_unhandled_exception.log",
            ["Exception"],
            alerts.append,
        )
        monitor.start()
        time.sleep(0.2)
        monitor.stop()
        assert len(alerts) >= 1
        assert any("exception" in a.lower() for a in alerts)

    def test_detects_traceback_pattern(self):
        """device_02: the Traceback pattern (with literal parens) matches correctly."""
        alerts = []
        monitor = fixture_monitor(
            "device_02_unhandled_exception.log",
            [r"Traceback \(most recent call last\)"],
            alerts.append,
        )
        monitor.start()
        time.sleep(0.2)
        monitor.stop()
        assert len(alerts) >= 1
        assert any("Traceback" in a for a in alerts)

    def test_detects_error_in_db_lost_log(self):
        """device_03: repeated ERROR lines from DB reconnect attempts all fire alerts,
        but seen-line dedup means each unique line only fires once."""
        alerts = []
        monitor = fixture_monitor("device_03_db_connection_lost.log", ["ERROR"], alerts.append)
        monitor.start()
        time.sleep(0.3)
        monitor.stop()
        assert len(alerts) >= 1
        assert all("ERROR" in a for a in alerts)

    def test_detects_slow_requests(self):
        """device_04: 'took XXXX ms' pattern fires on each unique slow-request line."""
        alerts = []
        monitor = fixture_monitor(
            "device_04_slow_request_storm.log",
            [r"took [1-9]\d{3,} ms"],
            alerts.append,
        )
        monitor.start()
        time.sleep(0.2)
        monitor.stop()
        assert len(alerts) >= 1
        assert all("took" in a and "ms" in a for a in alerts)

    def test_detects_fatal_on_startup_failure(self):
        """device_05: FATAL lines appear when DB is unreachable at startup."""
        alerts = []
        monitor = fixture_monitor("device_05_startup_failure.log", ["FATAL"], alerts.append)
        monitor.start()
        time.sleep(0.2)
        monitor.stop()
        assert len(alerts) >= 1
        assert all("FATAL" in a for a in alerts)

    def test_warning_lines_do_not_trigger_error_pattern(self):
        """device_03: WARNING lines (DB retry notice) must not match the ERROR pattern."""
        alerts = []
        monitor = fixture_monitor("device_03_db_connection_lost.log", ["ERROR"], alerts.append)
        monitor.start()
        time.sleep(0.2)
        monitor.stop()
        assert not any("WARNING" in a and "ERROR" not in a for a in alerts)
