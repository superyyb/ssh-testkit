import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from framework.parser import classify_result, classify_from_perl_json
 
 
class TestRunner:
    def __init__(self, ssh_client, tests):
        self.ssh_client = ssh_client
        self.tests = tests
        self.results = []
 
    def run_all(self, max_workers=1, on_result=None):
        """
        Run every test case in the test plan, concurrently if max_workers > 1.
        on_result: optional callback invoked immediately when each test completes.
                   Signature: on_result(result: dict) -> None
        """
        self.results = []
        if max_workers <= 1:
            for test in self.tests:
                result = self._run_one(test)
                self.results.append(result)
                if on_result:
                    on_result(result)
            return self.results
 
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self._run_one, test): test for test in self.tests}
            for future in as_completed(futures):
                result = future.result()
                self.results.append(result)
                if on_result:
                    on_result(result)
        return self.results
 
    def run_single(self, name):
        """Run one test case by name. Raises ValueError if not found."""
        for test in self.tests:
            if test["name"] == name:
                result = self._run_one(test)
                self.results.append(result)
                return result
        raise ValueError(f"Test case '{name}' not found in test plan.")
 
    def get_results(self):
        return self.results
 
    def _run_one(self, test):
        timeout      = test.get("timeout", 30)
        max_retries  = test.get("retries", 0)
        max_attempts = max_retries + 1
 
        # parser_type determines how to classify the output:
        # "regex"     → use regex pass/fail patterns (default)
        # "perl_json" → parse JSON output from parse_log.pl --json
        parser_type  = test.get("parser_type", "regex")
 
        logging.info(f"Running: {test['name']} "
                     f"(timeout={timeout}s, retries={max_retries}, parser={parser_type})")
 
        output  = None
        status  = "UNKNOWN"
        attempt = 0
 
        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                logging.info(f"  Retry {attempt-1}/{max_retries}...")
                time.sleep(1)
 
            try:
                output = self.ssh_client.run_command(test["command"], timeout=timeout)
 
                # Choose classifier based on parser_type
                if parser_type == "perl_json":
                    status = classify_from_perl_json(output)
                else:
                    status = classify_result(
                        output=output,
                        pass_regex=test.get("pass_regex"),
                        fail_regex=test.get("fail_regex")
                    )
 
            except Exception as e:
                logging.warning(f"  Attempt {attempt} error: {e}")
                output = {
                    "command":   test["command"],
                    "stdout":    "",
                    "stderr":    f"Timeout or connection error: {e}",
                    "exit_code": -1
                }
                status = "FAIL"
 
            if status == "PASS":
                break
 
            if attempt < max_attempts:
                logging.info(f"  Result: {status} — retrying...")
 
        logging.info(f"  -> {status} (attempt {attempt}/{max_attempts})")
 
        return {
            "name":        test["name"],
            "command":     test["command"],
            "status":      status,
            "stdout":      output["stdout"]    if output else "",
            "stderr":      output["stderr"]    if output else "",
            "exit_code":   output["exit_code"] if output else -1,
            "attempts":    attempt,
            "parser_type": parser_type,
        }