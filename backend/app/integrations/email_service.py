"""Email sending service using smtplib."""
import asyncio
import smtplib
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import encoders

from app.core.config import settings


async def send_email(
    to: str,
    subject: str,
    html_body: str,
    attachments: list[tuple[str, bytes, str]] | None = None,
) -> None:
    """Send an email with optional attachments.

    attachments: list of (filename, data, mimetype) tuples.
    Raises on SMTP failure so callers can catch and record the error.
    """
    if not settings.SMTP_HOST:
        raise RuntimeError("SMTP is not configured (SMTP_HOST is empty)")
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _send_sync, to, subject, html_body, attachments or [])


def _send_sync(
    to: str,
    subject: str,
    html_body: str,
    attachments: list[tuple[str, bytes, str]],
) -> None:
    msg = MIMEMultipart("mixed")
    msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    for filename, data, mimetype in attachments:
        main_type, sub_type = mimetype.split("/", 1)
        part = MIMEBase(main_type, sub_type)
        part.set_payload(data)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
        msg.attach(part)

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        if settings.SMTP_USER:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.sendmail(settings.SMTP_FROM, [to], msg.as_string())
