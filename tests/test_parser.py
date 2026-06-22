import pytest
from framework.parser import classify_result, extract_value


@pytest.fixture
def make_output():
    """Helper to build a fake command output dict."""
    def _make(stdout="", stderr="", exit_code=0):
        return {"stdout": stdout, "stderr": stderr, "exit_code": exit_code}
    return _make


# ── classify_result ────────────────────────────────────────────────────────

class TestClassifyResult:

    def test_pass(self, make_output):
        out = make_output(stdout="System check TEST_PASS")
        assert classify_result(out, "TEST_PASS", "ERROR|FAIL") == "PASS"

    def test_fail_pattern_beats_pass_pattern(self, make_output):
        # fail_regex is checked first — even if pass pattern also matches
        out = make_output(stdout="TEST_PASS but also ERROR occurred")
        assert classify_result(out, "TEST_PASS", "ERROR|FAIL") == "FAIL"

    def test_fail_via_stderr(self, make_output):
        out = make_output(stdout="", stderr="FATAL: device not responding")
        assert classify_result(out, "TEST_PASS", "FATAL|ERROR") == "FAIL"

    def test_fail_via_exit_code(self, make_output):
        # No regex matches, but non-zero exit code should still be FAIL
        out = make_output(stdout="no keywords here", exit_code=1)
        assert classify_result(out, "TEST_PASS", "ERROR") == "FAIL"

    def test_unknown_when_nothing_matches(self, make_output):
        out = make_output(stdout="no matching keyword", exit_code=0)
        assert classify_result(out, "TEST_PASS", "ERROR") == "UNKNOWN"

    def test_case_insensitive_matching(self, make_output):
        out = make_output(stdout="test_pass all good")
        assert classify_result(out, "TEST_PASS", "ERROR") == "PASS"

    def test_no_regexes_uses_exit_code(self, make_output):
        out = make_output(stdout="some output", exit_code=0)
        assert classify_result(out) == "UNKNOWN"

        out_fail = make_output(stdout="some output", exit_code=2)
        assert classify_result(out_fail) == "FAIL"


# ── Real-world patterns from test_plan.yaml ───────────────────────────────

class TestRealWorldPatterns:

    def test_disk_low_usage_passes(self, make_output):
        out = make_output(stdout="22%")
        assert classify_result(out, r"^[0-7]", r"^([89][0-9]|100)%") == "PASS"

    def test_disk_high_usage_fails(self, make_output):
        out = make_output(stdout="85%")
        assert classify_result(out, r"^[0-7]", r"^([89][0-9]|100)%") == "FAIL"

    def test_disk_single_digit_edge_case(self, make_output):
        # "8%" — first char not in [0-7], and [89][0-9] requires two digits → UNKNOWN
        out = make_output(stdout="8%")
        assert classify_result(out, r"^[0-7]", r"^([89][0-9]|100)%") == "UNKNOWN"

    def test_http_200_passes(self, make_output):
        out = make_output(stdout="200")
        assert classify_result(out, r"^200$", r"^[45]\d\d") == "PASS"

    def test_http_404_fails(self, make_output):
        out = make_output(stdout="404")
        assert classify_result(out, r"^200$", r"^[45]\d\d") == "FAIL"

    def test_http_500_fails(self, make_output):
        out = make_output(stdout="500")
        assert classify_result(out, r"^200$", r"^[45]\d\d") == "FAIL"

    def test_json_db_connected_passes(self, make_output):
        out = make_output(stdout='{"db": "connected", "service": "running"}')
        assert classify_result(out, r'"db":\s*"connected"', r'"db":\s*"unreachable"') == "PASS"

    def test_json_db_unreachable_fails(self, make_output):
        out = make_output(stdout='{"db": "unreachable", "service": "running"}')
        assert classify_result(out, r'"db":\s*"connected"', r'"db":\s*"unreachable"') == "FAIL"


# ── extract_value ──────────────────────────────────────────────────────────

class TestExtractValue:

    def test_extracts_captured_group(self, make_output):
        out = make_output(stdout="Temperature: 72 C")
        assert extract_value(out, r"Temperature: (\d+)") == "72"

    def test_returns_none_when_no_match(self, make_output):
        out = make_output(stdout="nothing here")
        assert extract_value(out, r"Temperature: (\d+)") is None

    def test_searches_stderr_too(self, make_output):
        out = make_output(stdout="", stderr="Voltage: 3.3V")
        assert extract_value(out, r"Voltage: ([\d.]+V)") == "3.3V"
