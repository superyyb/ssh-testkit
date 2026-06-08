import re
import json
 
 
def classify_result(output, pass_regex=None, fail_regex=None):
    """
    Classify a command result as PASS, FAIL, or UNKNOWN using regex.
 
    Priority order:
    1. fail_regex matches stdout or stderr  → FAIL
    2. pass_regex matches stdout or stderr  → PASS
    3. exit code != 0                       → FAIL
    4. otherwise                            → UNKNOWN
    """
    text = output["stdout"] + "\n" + output["stderr"]
 
    if fail_regex and re.search(fail_regex, text, re.IGNORECASE):
        return "FAIL"
 
    if pass_regex and re.search(pass_regex, text, re.IGNORECASE):
        return "PASS"
 
    if output["exit_code"] != 0:
        return "FAIL"
 
    return "UNKNOWN"
 
 
def classify_from_perl_json(output):
    """
    Classify result from parse_log.pl --json output.
 
    The Perl script outputs structured JSON; this function uses json.loads()
    to parse it and extract the result — no regex needed.
 
    Pipeline:
        SSH runs: perl parse_log.pl <log_file> --json
        Perl outputs JSON with timestamps, log levels, errors, result
        Python reads JSON → returns PASS / FAIL / UNKNOWN
    """
    try:
        data = json.loads(output["stdout"])
        return data.get("result", "UNKNOWN")
    except (json.JSONDecodeError, KeyError):
        return "UNKNOWN"
 
 
def extract_value(output, pattern):
    """
    Extract a captured group from command output using a regex pattern.
 
    Example:
        extract_value(output, r"Temperature: (\\d+)")  -> "72"
    """
    text = output["stdout"] + "\n" + output["stderr"]
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1) if match else None