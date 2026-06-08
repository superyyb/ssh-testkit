import os
from jinja2 import Environment, FileSystemLoader
from datetime import datetime


def generate_html_report(results, output_path="reports/report.html"):
    """Render an HTML report from test results using the Jinja2 template."""
    env = Environment(loader=FileSystemLoader("templates"))
    template = env.get_template("report.html.j2")

    html = template.render(
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        results=results,
        total=len(results),
        passed=sum(1 for r in results if r["status"] == "PASS"),
        failed=sum(1 for r in results if r["status"] == "FAIL"),
        unknown=sum(1 for r in results if r["status"] == "UNKNOWN")
    )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(html)

    return output_path
