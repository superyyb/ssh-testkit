"""
ci_analyze.py

Runs automatically in GitHub Actions when tests fail.
Reads the test run log, feeds it to Claude for analysis,
and prints a structured failure report to the CI output.
"""

import os
import sys
import glob
from langchain_anthropic import ChatAnthropic


def get_latest_log() -> str:
    """Find and read the most recent test run log."""
    logs = glob.glob("logs/*.log")
    if not logs:
        return ""
    latest = max(logs, key=os.path.getmtime)
    with open(latest) as f:
        return f.read()


def analyze(log_content: str) -> str:
    """Feed log content to Claude and return structured analysis."""
    llm = ChatAnthropic(model="claude-3-5-haiku-20241022", temperature=0)
    response = llm.invoke(
        "You are a CI test failure analyst. Analyze this test run log.\n\n"
        "Provide:\n"
        "1. Which tests failed and why\n"
        "2. Root cause of each failure\n"
        "3. Suggested fix for each failure\n"
        "4. Overall assessment (is this a flaky test, config issue, or real bug?)\n\n"
        f"Log:\n{log_content}"
    )
    return response.content


def main():
    print("\n" + "="*60)
    print("  AI Failure Diagnostics (LangChain + Claude)")
    print("="*60 + "\n")

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set — skipping AI analysis.")
        sys.exit(0)

    log_content = get_latest_log()

    if not log_content.strip():
        print("No log files found — skipping AI analysis.")
        sys.exit(0)

    print("Analyzing test failures...\n")
    analysis = analyze(log_content)
    print(analysis)
    print("\n" + "="*60 + "\n")


if __name__ == "__main__":
    main()
