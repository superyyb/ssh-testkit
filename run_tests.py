import argparse
import logging
import os
import time
import yaml
from datetime import datetime
 
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
    failed  = sum(1 for r in results if r["status"] == "FAIL")
    unknown = sum(1 for r in results if r["status"] == "UNKNOWN")
    label = f"Run #{run_index}" if run_index else "Results"
    print(f"\n{'='*40}")
    print(f"  {label}: {passed} PASS  {failed} FAIL  {unknown} UNKNOWN")
    print(f"{'='*40}\n")
 
 
def run_once(config, args, run_index=None):
    connection_cfg = config.get("connection", config.get("target", {}))
    tests = config["tests"]
 
    with build_client(connection_cfg) as client:
        runner = TestRunner(client, tests)
        if args.single:
            results = [runner.run_single(args.single)]
        else:
            max_workers = connection_cfg.get("max_workers", 1)

            def on_result(result):
                if result["status"] == "FAIL":
                    logging.warning(
                        f"[on_result] '{result['name']}' FAILED — triggering AI log analysis"
                    )
                    from framework.agent import analyze_log
                    analysis = analyze_log.invoke({"lines": 50})
                    logging.warning(f"[AI Analysis for '{result['name']}']\n{analysis}")

            results = runner.run_all(max_workers=max_workers, on_result=on_result)
 
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
 
    connection_cfg = config.get("connection", config.get("target", {}))
    monitor_cfg    = config.get("monitor", {})
    tests          = config["tests"]
 
    log_path      = monitor_cfg.get("log_path", "/home/testuser/device_logs/device.log")
    fail_patterns = monitor_cfg.get("fail_patterns", ["ERROR", "FATAL", "TEST_FAIL"])
    interval      = monitor_cfg.get("interval", 2)
 
    # Two separate SSH connections — one for tests, one for monitor
    test_client    = build_client(connection_cfg)
    monitor_client = build_client(connection_cfg)
    test_client.connect()
    monitor_client.connect()
 
    alerts = []
    def on_alert(line):
        alerts.append(line)
        print(f"\n  [ALERT] Failure detected in log: {line}")
        print(f"  [ALERT] Triggering AI analysis...")
        try:
            from langchain_openai import ChatOpenAI
            import os
            if os.getenv("OPENAI_API_KEY"):
                result   = monitor_client.run_command(f"tail -n 50 {log_path}")
                llm      = ChatOpenAI(model="gpt-4o-mini", temperature=0)
                response = llm.invoke(
                    f"A failure was detected in a device log. Analyze the following log and explain:\n"
                    f"1. What failed and why\n"
                    f"2. How severe is it\n"
                    f"3. Suggested fix\n\n"
                    f"Triggering line: {line}\n\n"
                    f"Log context:\n{result['stdout']}"
                )
                print(f"\n  [AI Analysis]\n{response.content}\n")
            else:
                print("  [AI Analysis] Skipped — OPENAI_API_KEY not set\n")
        except Exception as e:
            print(f"  [AI Analysis] Failed: {e}\n")
 
    monitor = LogMonitor(
        ssh_client=monitor_client,
        log_path=log_path,
        fail_patterns=fail_patterns,
        alert_callback=on_alert,
        interval=interval
    )
 
    try:
        print(f"[Concurrent mode] Running tests + monitoring {log_path}\n")
        monitor.start()
        runner      = TestRunner(test_client, tests)
        max_workers = connection_cfg.get("max_workers", 1)
        results     = runner.run_all(max_workers=max_workers)
        monitor.stop()
    finally:
        test_client.close()
        monitor_client.close()
 
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