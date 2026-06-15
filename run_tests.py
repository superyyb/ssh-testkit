import argparse
import logging
import os
import time
import threading
import yaml
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
 
from framework.test_runner import TestRunner
from framework.reporter import generate_html_report
from framework.emailer import send_email_report
 
 
def setup_logging():
    os.makedirs("logs", exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler("logs/test_run.log"),
            logging.StreamHandler()
        ]
    )
 
 
def load_config(path):
    with open(path) as f:
        return yaml.safe_load(f)
 
 
def build_client(connection_cfg):
    conn_type = connection_cfg.get("type", "ssh")
    if conn_type == "serial":
        from framework.serial_client import SerialClient
        return SerialClient(
            port=connection_cfg["port"],
            baudrate=connection_cfg.get("baudrate", 115200),
            prompt=connection_cfg.get("prompt", "$ ")
        )
    else:
        from framework.ssh_client import SSHClient
        return SSHClient(
            host=connection_cfg["host"],
            port=connection_cfg["port"],
            username=connection_cfg["username"],
            password=connection_cfg["password"]
        )
 
 
def print_summary(results, run_index=None):
    passed  = sum(1 for r in results if r["status"] == "PASS")
    flaky   = sum(1 for r in results if r["status"] == "FLAKY")
    failed  = sum(1 for r in results if r["status"] == "FAIL")
    unknown = sum(1 for r in results if r["status"] == "UNKNOWN")
    label = f"Run #{run_index}" if run_index else "Results"
    print(f"\n{'='*40}")
    print(f"  {label}: {passed} PASS  {flaky} FLAKY  {failed} FAIL  {unknown} UNKNOWN")
    print(f"{'='*40}\n")
 
 
def run_once(config, args, run_index=None):
    _started_at    = datetime.now()
    connection_cfg = config.get("connection", config.get("target", {}))
    tests          = config["tests"]

    _db_run_id = None
    try:
        from framework.database import init_schema, create_test_run
        init_schema()
        _db_run_id = create_test_run(getattr(args, "config", "unknown"))
    except Exception as e:
        logging.warning(f"[DB] Unavailable, skipping persistence: {e}")

    # ThreadPoolExecutor for async AI analysis — keeps test workers unblocked
    _ai_executor  = ThreadPoolExecutor(max_workers=3)
    _ai_futures   = []
    _ssh_lock     = threading.Lock()  # prevents concurrent client.run_command() calls
    _analysis_llm = None
    if os.getenv("ANTHROPIC_API_KEY"):
        from langchain_anthropic import ChatAnthropic
        _analysis_llm = ChatAnthropic(model=os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-20241022"), temperature=0)

    def _run_ai_analysis_once(test_name, log_content, result_id=None):
        """AI analysis in a background thread — does not block test workers."""
        try:
            log_context = log_content.get("stdout", "").strip() or "(no log output available)"
            response    = _analysis_llm.invoke(
                f"A test failed. Analyze the following device log and explain:\n"
                f"1. What failed and why\n"
                f"2. How severe is it\n"
                f"3. Suggested fix\n\n"
                f"Failed test: {test_name}\n\n"
                f"Log context:\n{log_context}"
            )
            logging.warning(f"[AI Analysis for '{test_name}']\n{response.content}")
            print(f"\n  [AI Analysis for '{test_name}']\n{response.content}\n")
            if _db_run_id and result_id:
                try:
                    from framework.database import update_result_ai
                    update_result_ai(result_id, response.content)
                except Exception as db_err:
                    logging.warning(f"[DB] update_result_ai failed: {db_err}")
        except Exception as e:
            logging.exception(f"[AI Analysis] Failed for '{test_name}': {e}")

    with build_client(connection_cfg) as client:
        runner = TestRunner(client, tests)
        if args.single:
            results = [runner.run_single(args.single)]
        else:
            max_workers = connection_cfg.get("max_workers", 1)

            def on_result(result):
                result_id = None
                if _db_run_id:
                    try:
                        from framework.database import save_test_result
                        result_id = save_test_result(_db_run_id, result)
                    except Exception as db_err:
                        logging.warning(f"[DB] save_test_result failed: {db_err}")

                if result["status"] == "FAIL":
                    logging.warning(
                        f"[on_result] '{result['name']}' FAILED — triggering async AI log analysis"
                    )
                    if _analysis_llm:
                        log_cfg  = config.get("monitor", {})
                        log_path = log_cfg.get("log_path", "/home/testuser/app_logs/app.log")
                        with _ssh_lock:
                            log_data = client.run_command(f"tail -n 50 {log_path}")
                        _ai_futures.append(
                            _ai_executor.submit(_run_ai_analysis_once, result["name"], log_data, result_id)
                        )

            results = runner.run_all(max_workers=max_workers, on_result=on_result)

    # Wait up to 30s per pending AI analysis; skip if it takes too long
    for f in _ai_futures:
        try:
            f.result(timeout=30)
        except Exception:
            pass
    _ai_executor.shutdown(wait=True)

    if _db_run_id:
        try:
            from framework.database import finish_test_run
            finish_test_run(_db_run_id, results, _started_at)
        except Exception as e:
            logging.warning(f"[DB] finish_test_run failed: {e}")

    timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = generate_html_report(results, output_path=f"reports/report_{timestamp}.html")
    logging.info(f"Report saved: {report_path}")
    print_summary(results, run_index)
 
    if args.email:
        email_cfg = config.get("email", {})
        if not email_cfg.get("enabled"):
            print("Email disabled in config. Set email.enabled: true to send.")
        else:
            send_email_report(
                report_path=report_path,
                sender=email_cfg["sender"],
                receiver=email_cfg["receiver"],
                subject=email_cfg.get("subject", "Test Report"),
                smtp_server=email_cfg["smtp_server"],
                smtp_port=email_cfg["smtp_port"]
            )
    return results, report_path
 
 
def run_with_monitor(config, args):
    """
    Run tests and monitor log file concurrently using two threads.
    Thread 1 (main): executes the test suite
    Thread 2 (daemon): polls the log file for failure patterns in real-time
    """
    from framework.log_monitor import LogMonitor
    _started_at = datetime.now()

    connection_cfg = config.get("connection", config.get("target", {}))
    monitor_cfg    = config.get("monitor", {})
    tests          = config["tests"]
 
    log_path      = monitor_cfg.get("log_path", "/home/testuser/device_logs/device.log")
    fail_patterns = monitor_cfg.get("fail_patterns", ["ERROR", "FATAL", "TEST_FAIL"])
    interval      = monitor_cfg.get("interval", 2)

    _db_run_id = None
    try:
        from framework.database import init_schema, create_test_run
        init_schema()
        _db_run_id = create_test_run(getattr(args, "config", "unknown"))
    except Exception as e:
        logging.warning(f"[DB] Unavailable, skipping persistence: {e}")

    # Two separate SSH connections — one for tests, one for monitor
    test_client    = build_client(connection_cfg)
    monitor_client = build_client(connection_cfg)
    test_client.connect()
    monitor_client.connect()
 
    # ThreadPoolExecutor limits concurrent AI analysis to 3 threads max
    # prevents API rate limits and resource exhaustion on repeated failures
    _ai_executor = ThreadPoolExecutor(max_workers=3)
    _ai_futures  = []
    _ssh_lock    = threading.Lock()
    llm = None
    if os.getenv("ANTHROPIC_API_KEY"):
        from langchain_anthropic import ChatAnthropic
        llm = ChatAnthropic(model=os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-20241022"), temperature=0)
 
    def _run_ai_analysis(alert_line, alert_id=None):
        """Run in a background thread — reuses monitor_client with a lock to avoid race conditions."""
        try:
            with _ssh_lock:
                result = monitor_client.run_command(f"tail -n 50 {log_path}")
            log_context = result.get('stdout', '').strip() or '(no log output available)'
            response = llm.invoke(
                f"A failure was detected in a device log. Analyze the following log and explain:\n"
                f"1. What failed and why\n"
                f"2. How severe is it\n"
                f"3. Suggested fix\n\n"
                f"Triggering line: {alert_line}\n\n"
                f"Log context:\n{log_context}"
            )
            logging.warning(f"[AI Analysis]\n{response.content}")
            print(f"\n  [AI Analysis]\n{response.content}\n")
            if _db_run_id and alert_id:
                try:
                    from framework.database import update_alert_ai
                    update_alert_ai(alert_id, response.content)
                except Exception as db_err:
                    logging.warning(f"[DB] update_alert_ai failed: {db_err}")
        except Exception as e:
            logging.exception(f"[AI Analysis] Failed: {e}")
            print(f"  [AI Analysis] Failed: {e}\n")
 
    alerts = []
    def on_alert(line):
        alerts.append(line)
        print(f"\n  [ALERT] Failure detected in log: {line}\n")
        alert_id = None
        if _db_run_id:
            try:
                from framework.database import save_alert_event
                alert_id = save_alert_event(_db_run_id, line)
            except Exception as db_err:
                logging.warning(f"[DB] save_alert_event failed: {db_err}")
        if llm:
            print(f"  [ALERT] Triggering AI analysis in background...\n")
            _ai_futures.append(_ai_executor.submit(_run_ai_analysis, line, alert_id))
        else:
            print("  [AI Analysis] Skipped — ANTHROPIC_API_KEY not set\n")
 
    monitor = LogMonitor(
        ssh_client=monitor_client,
        log_path=log_path,
        fail_patterns=fail_patterns,
        alert_callback=on_alert,
        interval=interval
    )
 
    def on_result(result):
        if _db_run_id:
            try:
                from framework.database import save_test_result
                save_test_result(_db_run_id, result)
            except Exception as db_err:
                logging.warning(f"[DB] save_test_result failed: {db_err}")

    try:
        print(f"[Concurrent mode] Running tests + monitoring {log_path}\n")
        monitor.start()
        runner      = TestRunner(test_client, tests)
        max_workers = connection_cfg.get("max_workers", 1)
        results     = runner.run_all(max_workers=max_workers, on_result=on_result)
        monitor.stop()
    finally:
        test_client.close()
        monitor_client.close()
        # Wait up to 30s per pending AI analysis; skip if it takes too long
        for f in _ai_futures:
            try:
                f.result(timeout=30)
            except Exception:
                pass
        _ai_executor.shutdown(wait=True)

    if _db_run_id:
        try:
            from framework.database import finish_test_run
            finish_test_run(_db_run_id, results, _started_at)
        except Exception as e:
            logging.warning(f"[DB] finish_test_run failed: {e}")

    timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = generate_html_report(results, output_path=f"reports/report_{timestamp}.html")
    logging.info(f"Report saved: {report_path}")
    print_summary(results)
 
    if alerts:
        print(f"[Monitor] {len(alerts)} failure(s) detected during run:")
        for a in alerts:
            print(f"  {a}")
 
    return results, report_path
 
 
def main():
    parser = argparse.ArgumentParser(description="Linux Test Automation Framework")
    parser.add_argument("--config",   required=True,        help="Path to test plan YAML")
    parser.add_argument("--single",                         help="Run a single test case by name")
    parser.add_argument("--email",    action="store_true",  help="Send email after each run")
    parser.add_argument("--loop",     action="store_true",  help="Run continuously until Ctrl+C")
    parser.add_argument("--interval", type=int, default=60, help="Seconds between loop runs (default: 60)")
    parser.add_argument("--monitor",  action="store_true",  help="Run tests + monitor log concurrently")
    parser.add_argument("--agent",    action="store_true",  help="Start interactive AI agent")
    args = parser.parse_args()
 
    setup_logging()
    config = load_config(args.config)
 
    # ── Agent mode ────────────────────────────────────────────────────────────
    if args.agent:
        from framework.agent import start_agent
        start_agent(config)
        return
 
    # ── Concurrent mode ───────────────────────────────────────────────────────
    if args.monitor:
        run_with_monitor(config, args)
        return
 
    # ── Loop mode ─────────────────────────────────────────────────────────────
    if args.loop:
        print(f"Loop mode: running every {args.interval}s. Press Ctrl+C to stop.\n")
        run_index = 1
        try:
            while True:
                logging.info(f"--- Starting run #{run_index} ---")
                run_once(config, args, run_index)
                run_index += 1
                print(f"Next run in {args.interval}s... (Ctrl+C to stop)")
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print(f"\nStopped after {run_index - 1} run(s).")
        return
 
    # ── Single run (default) ──────────────────────────────────────────────────
    run_once(config, args)
 
 
if __name__ == "__main__":
    main()