"""
Unit tests for LogMonitor — pattern matching, alert callback, seen-line dedup.
Uses a mock SSH client so no real SSH connection is needed.
"""
import time
import pytest
from unittest.mock import MagicMock
from framework.log_monitor import LogMonitor


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
