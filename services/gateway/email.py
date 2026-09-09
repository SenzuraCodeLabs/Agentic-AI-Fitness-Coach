"""Transactional email over Gmail SMTP.

Uses ``aiosmtplib`` rather than ``smtplib`` because the latter blocks the event
loop for the duration of the SMTP conversation, which on a remote server is
hundreds of milliseconds during which the whole service stalls.

STARTTLS on port 587 upgrades the connection before authentication, so the app
password never crosses the wire in the clear.

Failures are logged and swallowed at the call site: a user who registered
successfully should not see a 500 because the mail server was briefly
unreachable. They can request another verification link.
"""

from __future__ import annotations

from email.message import EmailMessage

import aiosmtplib

from shared.config import get_settings
from shared.logging import get_logger

log = get_logger("gateway.email")

_BASE_STYLE = (
    "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;"
    "max-width:520px;margin:0 auto;padding:24px;color:#1a1a1a;line-height:1.6"
)
_BUTTON_STYLE = (
    "display:inline-block;padding:12px 24px;background:#111;color:#fff;"
    "text-decoration:none;border-radius:6px;font-weight:600"
)


async def send_email(to: str, subject: str, html: str, text: str) -> bool:
    """Send one message. Returns False on failure rather than raising."""
    settings = get_settings()

    if not settings.smtp_user or not settings.smtp_password.get_secret_value():
        log.warning("email_not_configured", to_domain=to.split("@")[-1])
        return False

    message = EmailMessage()
    message["From"] = settings.smtp_from or settings.smtp_user
    message["To"] = to
    message["Subject"] = subject
    # A plain-text alternative is set first so clients that do not render HTML
    # still receive a usable message.
    message.set_content(text)
    message.add_alternative(html, subtype="html")

    try:
        await aiosmtplib.send(
            message,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user,
            password=settings.smtp_password.get_secret_value(),
            start_tls=True,
            timeout=15,
        )
        # The recipient address is not logged in full: it is personal data, and
        # logs are the exact place it should not accumulate.
        log.info("email_sent", subject=subject, to_domain=to.split("@")[-1])
        return True
    except (aiosmtplib.SMTPException, OSError, TimeoutError) as exc:
        log.error("email_send_failed", error=type(exc).__name__, subject=subject)
        return False


def _wrap(title: str, body_html: str) -> str:
    return (
        f'<div style="{_BASE_STYLE}">'
        f'<h2 style="margin:0 0 16px">{title}</h2>'
        f"{body_html}"
        '<hr style="border:none;border-top:1px solid #eee;margin:28px 0">'
        '<p style="font-size:12px;color:#888;margin:0">'
        "FitCoach, a student project for SLIIT IT3041. "
        "If you did not request this, no action is needed."
        "</p></div>"
    )


async def send_verification_email(to: str, token: str, base_url: str) -> bool:
    link = f"{base_url.rstrip('/')}/verify-email?token={token}"
    html = _wrap(
        "Confirm your email",
        f"<p>Welcome to FitCoach. Confirm this address to start logging sessions.</p>"
        f'<p style="margin:24px 0"><a href="{link}" style="{_BUTTON_STYLE}">Confirm email</a></p>'
        f'<p style="font-size:13px;color:#666">Or paste this link into your browser:<br>'
        f'<span style="word-break:break-all">{link}</span></p>'
        f'<p style="font-size:13px;color:#666">This link works once and expires in 24 hours.</p>',
    )
    text = (
        "Welcome to FitCoach.\n\n"
        f"Confirm your email address:\n{link}\n\n"
        "This link works once and expires in 24 hours."
    )
    return await send_email(to, "Confirm your FitCoach email", html, text)


async def send_password_reset_email(to: str, token: str, base_url: str) -> bool:
    link = f"{base_url.rstrip('/')}/reset-password?token={token}"
    html = _wrap(
        "Reset your password",
        f"<p>Use the button below to choose a new password.</p>"
        f'<p style="margin:24px 0"><a href="{link}" style="{_BUTTON_STYLE}">Reset password</a></p>'
        f'<p style="font-size:13px;color:#666">Or paste this link into your browser:<br>'
        f'<span style="word-break:break-all">{link}</span></p>'
        f'<p style="font-size:13px;color:#666">This link works once and expires in 1 hour. '
        f"Your current password stays active until you choose a new one.</p>",
    )
    text = f"Reset your FitCoach password:\n{link}\n\nThis link works once and expires in 1 hour."
    return await send_email(to, "Reset your FitCoach password", html, text)


async def send_weekly_digest(
    to: str, *, tonnage_kg: float, sessions: int, prs: list[str], targets: list[str]
) -> bool:
    """Weekly summary. Sent only to users who have not opted out."""
    pr_html = (
        "".join(f"<li>{p}</li>" for p in prs)
        if prs
        else "<li>No new personal records this week.</li>"
    )
    target_html = "".join(f"<li>{t}</li>" for t in targets) or "<li>Keep training.</li>"

    html = _wrap(
        "Your training week",
        f"<p><strong>{sessions}</strong> sessions, <strong>{tonnage_kg:,.0f} kg</strong> "
        f"total tonnage.</p>"
        f"<h3 style='font-size:15px;margin:20px 0 8px'>Personal records</h3><ul>{pr_html}</ul>"
        f"<h3 style='font-size:15px;margin:20px 0 8px'>Next week</h3><ul>{target_html}</ul>"
        "<p style='font-size:12px;color:#888;margin-top:24px'>"
        "You can turn these off in your account settings.</p>",
    )
    text = (
        f"Your training week\n\n{sessions} sessions, {tonnage_kg:,.0f} kg total tonnage.\n\n"
        f"Personal records:\n" + ("\n".join(f"- {p}" for p in prs) or "- None this week") + "\n\n"
        "Next week:\n" + ("\n".join(f"- {t}" for t in targets) or "- Keep training")
    )
    return await send_email(to, "Your FitCoach week", html, text)
