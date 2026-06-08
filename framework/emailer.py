import smtplib
import logging
from email.message import EmailMessage


def send_email_report(report_path, sender, receiver, subject, smtp_server, smtp_port):
    """
    Send the HTML report as an email attachment.

    For local testing, start Python's debug SMTP server first:
        python -m smtpd -c DebuggingServer -n localhost:1025
    """
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = receiver
    msg["Subject"] = subject
    msg.set_content("Test run complete. See attached HTML report.")

    with open(report_path, "r") as f:
        html_content = f.read()

    msg.add_attachment(
        html_content,
        maintype="text",
        subtype="html",
        filename="report.html"
    )

    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.send_message(msg)

    logging.info(f"Report emailed to {receiver} via {smtp_server}:{smtp_port}")
