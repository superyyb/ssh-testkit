# Linux Test Automation Framework

A Python CLI framework that SSH-connects to Linux targets, runs configurable test suites, parses command output with regex, generates HTML reports, and sends email notifications.

## Quick start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Start the simulated device
```bash
cd docker
docker compose up --build
```
This starts an Ubuntu container with SSH on `localhost:2222`.

### 3. Run all tests
```bash
python run_tests.py --config configs/test_plan.yaml
```

### 4. Run a single test
```bash
python run_tests.py --config configs/test_plan.yaml --single "Check disk usage"
```

### 5. Run tests and send email
Start the local debug SMTP server in a separate terminal:
```bash
python -m smtpd -c DebuggingServer -n localhost:1025
```
Set `email.enabled: true` in your config, then:
```bash
python run_tests.py --config configs/test_plan.yaml --email
```

### 6. Run unit tests
```bash
pytest
```

## Project structure
```
linux-test-automation-framework/
├── run_tests.py          # CLI entry point
├── configs/
│   └── test_plan.yaml    # Test cases + device + email config
├── framework/
│   ├── ssh_client.py     # paramiko SSH wrapper
│   ├── test_runner.py    # Orchestrates test execution
│   ├── parser.py         # regex-based pass/fail classification
│   ├── reporter.py       # jinja2 HTML report generation
│   └── emailer.py        # smtplib email delivery
├── templates/
│   └── report.html.j2    # HTML report template
├── docker/
│   ├── Dockerfile        # Simulated Linux target
│   └── docker-compose.yml
├── logs/                 # Generated run logs
├── reports/              # Generated HTML reports
└── tests/
    └── test_parser.py    # pytest unit tests
```

## Adding test cases
Edit `configs/test_plan.yaml`:
```yaml
tests:
  - name: My new test
    command: some-linux-command
    pass_regex: "expected output"
    fail_regex: "error|failed"
```
No code changes needed.
