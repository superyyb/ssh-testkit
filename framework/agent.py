import os
import time
import logging
from datetime import datetime
from typing import Optional
 
from langchain_anthropic import ChatAnthropic
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from dotenv import load_dotenv
 
load_dotenv()
 
from framework.ssh_client import SSHClient
from framework.test_runner import TestRunner
from framework.reporter import generate_html_report
from framework.emailer import send_email_report
 
 
# ── Session state ─────────────────────────────────────────────────────────────
 
_runner: Optional[TestRunner] = None
_ssh: Optional[SSHClient] = None
_last_results: list = []
_report_path: Optional[str] = None
_config: dict = {}
 
 
def _require_runner():
    if _runner is None:
        raise RuntimeError("Not connected. Agent session not started properly.")
    return _runner
 
 
# ── Tools ─────────────────────────────────────────────────────────────────────
 
@tool
def list_tests() -> str:
    """List all available test cases in the current test plan."""
    tests = _config.get("tests", [])
    if not tests:
        return "No test cases found in config."
    lines = [f"  {i+1}. {t['name']}" for i, t in enumerate(tests)]
    return "Available tests:\n" + "\n".join(lines)
 
 
@tool
def run_all_tests() -> str:
    """Run all test cases and return a summary of results. If any tests fail, automatically triggers AI log analysis."""
    global _last_results
    _last_results = _require_runner().run_all()
 
    passed  = sum(1 for r in _last_results if r["status"] == "PASS")
    failed  = sum(1 for r in _last_results if r["status"] == "FAIL")
    unknown = sum(1 for r in _last_results if r["status"] == "UNKNOWN")
 
    lines = [f"  {r['name']}: {r['status']}" for r in _last_results]
    summary = (
        f"Ran {len(_last_results)} tests — "
        f"{passed} PASS, {failed} FAIL, {unknown} UNKNOWN\n"
        + "\n".join(lines)
    )
 
    if failed > 0:
        logging.warning(f"{failed} test(s) failed — triggering automatic AI log analysis")
        ai_analysis = analyze_log.invoke({"lines": 50})
        summary += f"\n\n[Auto AI Analysis]\n{ai_analysis}"
 
    return summary
 
 
@tool
def run_single_test(name: str) -> str:
    """Run one test case by its exact name and return the result."""
    global _last_results
    try:
        result = _require_runner().run_single(name)
        _last_results = [result]
        stdout_preview = result["stdout"][:300] if result["stdout"] else "(empty)"
        return (
            f"{result['name']}: {result['status']}\n"
            f"exit code: {result['exit_code']}\n"
            f"stdout:\n{stdout_preview}"
        )
    except ValueError as e:
        available = [t["name"] for t in _config.get("tests", [])]
        return f"{e}\nAvailable tests: {', '.join(available)}"
 
 
@tool
def get_last_results() -> str:
    """Return a summary of the most recent test run."""
    if not _last_results:
        return "No tests have been run yet in this session."
    passed  = sum(1 for r in _last_results if r["status"] == "PASS")
    failed  = sum(1 for r in _last_results if r["status"] == "FAIL")
    unknown = sum(1 for r in _last_results if r["status"] == "UNKNOWN")
    lines = [f"  {r['name']}: {r['status']}" for r in _last_results]
    return (
        f"Last run: {passed} PASS, {failed} FAIL, {unknown} UNKNOWN\n"
        + "\n".join(lines)
    )
 
 
@tool
def show_test_output(name: str) -> str:
    """Show the full stdout and stderr for a specific test from the last run."""
    for r in _last_results:
        if r["name"].lower() == name.lower():
            out = (
                f"Test:      {r['name']}\n"
                f"Status:    {r['status']}\n"
                f"Exit code: {r['exit_code']}\n\n"
                f"STDOUT:\n{r['stdout'] or '(empty)'}"
            )
            if r["stderr"]:
                out += f"\nSTDERR:\n{r['stderr']}"
            return out
    return f"Test '{name}' not found in last results. Run the test first."
 
 
@tool
def generate_report() -> str:
    """Generate an HTML report from the last test run and save it to reports/."""
    global _report_path
    if not _last_results:
        return "No results available. Run the tests first."
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    _report_path = generate_html_report(
        _last_results,
        output_path=f"reports/report_{timestamp}.html"
    )
    return f"Report generated: {_report_path}"
 
 
@tool
def send_report(email_address: str) -> str:
    """Send the most recently generated HTML report to the given email address."""
    if not _report_path:
        return "No report generated yet. Call generate_report first."
    email_cfg = _config.get("email", {})
    try:
        send_email_report(
            report_path=_report_path,
            sender=email_cfg.get("sender", "test-bot@example.com"),
            receiver=email_address,
            subject=email_cfg.get("subject", "Test Automation Report"),
            smtp_server=email_cfg.get("smtp_server", "localhost"),
            smtp_port=email_cfg.get("smtp_port", 1025)
        )
        return f"Report sent to {email_address}."
    except Exception as e:
        return f"Failed to send email: {e}"
 
 
@tool
def monitor_tests(interval_seconds: int, max_runs: int, alert_email: str = "") -> str:
    """
    Run all tests repeatedly on a schedule.
    Sends an email alert automatically whenever any test fails.
    Stops after max_runs iterations.
    """
    global _last_results, _report_path
 
    runner    = _require_runner()
    email_cfg = _config.get("email", {})
    summary_lines = []
 
    print(f"\n[Monitor] Starting: {max_runs} runs every {interval_seconds}s. Ctrl+C to stop.\n")
 
    for run_num in range(1, max_runs + 1):
        print(f"[Monitor] Run #{run_num}/{max_runs}...")
        _last_results = runner.run_all()
 
        passed  = sum(1 for r in _last_results if r["status"] == "PASS")
        failed  = sum(1 for r in _last_results if r["status"] == "FAIL")
        unknown = sum(1 for r in _last_results if r["status"] == "UNKNOWN")
 
        line = f"  Run #{run_num}: {passed} PASS  {failed} FAIL  {unknown} UNKNOWN"
        print(line)
        summary_lines.append(line)
 
        if failed > 0 and alert_email:
            timestamp    = datetime.now().strftime("%Y%m%d_%H%M%S")
            _report_path = generate_html_report(
                _last_results,
                output_path=f"reports/report_{timestamp}.html"
            )
            try:
                send_email_report(
                    report_path=_report_path,
                    sender=email_cfg.get("sender", "test-bot@example.com"),
                    receiver=alert_email,
                    subject=f"[ALERT] Test failure detected — Run #{run_num}",
                    smtp_server=email_cfg.get("smtp_server", "localhost"),
                    smtp_port=email_cfg.get("smtp_port", 1025)
                )
                print(f"  [Alert] Failure email sent to {alert_email}")
            except Exception as e:
                print(f"  [Alert] Failed to send email: {e}")
 
        if run_num < max_runs:
            time.sleep(interval_seconds)
 
    print("[Monitor] Done.\n")
    return (
        f"Monitor complete: {max_runs} runs\n"
        + "\n".join(summary_lines)
    )
 
 
@tool
def capture_log(lines: int = 50) -> str:
    """
    Capture the most recent lines from the device log file.
    Returns raw log content for inspection or further analysis.
    """
    runner = _require_runner()
    log_path = _config.get("monitor", {}).get(
        "log_path", "/home/testuser/device_logs/device.log"
    )
    result = runner.ssh_client.run_command(f"tail -n {lines} {log_path}")
    if not result["stdout"].strip():
        return "Log file is empty or not found."
    return result["stdout"]
 
 
@tool
def analyze_log(lines: int = 50) -> str:
    """
    Capture device log and feed it to AI for analysis.
    Internally calls capture_log to get raw data, then sends it to the LLM.
    Returns a structured analysis: overall status, errors found, and summary.
    """
    # Step 1: capture the log (tool calling tool pattern)
    runner   = _require_runner()
    log_path = _config.get("monitor", {}).get(
        "log_path", "/home/testuser/device_logs/device.log"
    )
    result      = runner.ssh_client.run_command(f"tail -n {lines} {log_path}")
    log_content = result["stdout"]
 
    if not log_content.strip():
        return "Log file is empty or not found."
 
    # Step 2: feed log to AI for analysis
    analysis_llm = ChatAnthropic(model="claude-3-5-haiku-20241022", temperature=0)
    response = analysis_llm.invoke(
        f"You are a hardware test log analyzer. Analyze this device log:\n\n"
        f"{log_content}\n\n"
        f"Provide:\n"
        f"1. Overall status (PASS / FAIL / WARNING)\n"
        f"2. Any errors or failures found\n"
        f"3. Any patterns or anomalies worth noting\n"
        f"4. A 2-3 sentence summary"
    )
    return response.content
 
 
# ── Agent entry point ─────────────────────────────────────────────────────────
 
def start_agent(config: dict):
    """
    Start an interactive agent session.
    Maintains a single SSH connection for the whole conversation.
    """
    global _runner, _ssh, _config
    _config = config
 
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise EnvironmentError(
            "ANTHROPIC_API_KEY not set.\n"
            "Add it to your .env file: ANTHROPIC_API_KEY=sk-ant-api03-..."
        )
 
    target = config.get("connection", config.get("target", {}))
    _ssh   = SSHClient(
        host=target["host"],
        port=target["port"],
        username=target["username"],
        password=target["password"]
    )
    _ssh.connect()
    _runner = TestRunner(_ssh, config["tests"])
    logging.info("Agent: SSH connection established")
 
    llm = ChatAnthropic(model="claude-3-5-haiku-20241022", temperature=0)
 
    tools = [
        list_tests,
        run_all_tests,
        run_single_test,
        get_last_results,
        show_test_output,
        generate_report,
        send_report,
        monitor_tests,
        capture_log,
        analyze_log,
    ]
 
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a test automation assistant for a Linux device test framework.
You help the user run tests, inspect results, generate HTML reports, and send email notifications.
 
Available tools:
- list_tests: show available test cases
- run_all_tests: run the full test suite
- run_single_test: run one test by name
- get_last_results: summarize the last run
- show_test_output: show stdout/stderr for a specific test
- generate_report: create an HTML report
- send_report: email the report
- monitor_tests: run tests on a schedule with auto failure alerts
- capture_log: read raw device log content
- analyze_log: capture log and use AI to analyze it for failures and anomalies
 
Be concise and action-oriented. Execute immediately without asking for confirmation.
For log analysis requests, use analyze_log. For just reading logs, use capture_log.
For monitoring tasks like 'run every X seconds', use monitor_tests."""),
        ("human", "{input}"),
        ("placeholder", "{agent_scratchpad}"),
    ])
 
    agent    = create_tool_calling_agent(llm, tools, prompt)
    executor = AgentExecutor(agent=agent, tools=tools, verbose=False)
 
    print("\n" + "="*50)
    print("  Test Automation Agent  (10 tools)")
    print("  Type 'exit' to quit")
    print("="*50)
    print("  Try: 'run all tests'")
    print("       'analyze the log'")
    print("       'monitor every 30s for 5 runs, alert me@company.com on failure'")
    print("       'generate report and send to me@company.com'")
    print("="*50 + "\n")
 
    try:
        while True:
            try:
                user_input = input("You: ").strip()
            except EOFError:
                break
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "q"):
                break
            response = executor.invoke({"input": user_input})
            print(f"\nAgent: {response['output']}\n")
    finally:
        _ssh.close()
        print("Session ended.")