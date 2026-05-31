"""Minimal email sender for account-activation messages.

Sends via SMTP when configured through the environment; otherwise falls back to
logging the activation URL (so local / dev deployments work without a mail
server). Configuration (all optional except host to actually send):

    FRETWISE_SMTP_HOST, FRETWISE_SMTP_PORT (default 587)
    FRETWISE_SMTP_USER, FRETWISE_SMTP_PASSWORD
    FRETWISE_SMTP_FROM (default "no-reply@fretwise.local")
    FRETWISE_SMTP_TLS  ("1"/"0", default "1" = STARTTLS)
"""

from __future__ import annotations

import logging
import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SmtpConfig:
    host: str = ""
    port: int = 587
    user: str = ""
    password: str = ""
    sender: str = "no-reply@fretwise.local"
    use_tls: bool = True

    @property
    def configured(self) -> bool:
        return bool(self.host)


def load_smtp_config() -> SmtpConfig:
    return SmtpConfig(
        host=os.environ.get("FRETWISE_SMTP_HOST", ""),
        port=int(os.environ.get("FRETWISE_SMTP_PORT", "587") or "587"),
        user=os.environ.get("FRETWISE_SMTP_USER", ""),
        password=os.environ.get("FRETWISE_SMTP_PASSWORD", ""),
        sender=os.environ.get("FRETWISE_SMTP_FROM", "no-reply@fretwise.local"),
        use_tls=os.environ.get("FRETWISE_SMTP_TLS", "1").strip().lower()
        in {"1", "true", "yes", "on"},
    )


def _build_message(cfg: SmtpConfig, to_email: str, activation_url: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = "Activate your FretWise account"
    msg["From"] = cfg.sender
    msg["To"] = to_email
    msg.set_content(
        "Welcome to FretWise!\n\n"
        "Please confirm your email address by opening this link:\n\n"
        f"{activation_url}\n\n"
        "This link expires in 24 hours. If you did not create an account, "
        "you can ignore this message.\n"
    )
    return msg


def send_activation_email(
    to_email: str,
    activation_url: str,
    *,
    config: SmtpConfig | None = None,
) -> bool:
    """Send (or log) the activation email. Returns True if actually sent by SMTP.

    Never raises on SMTP failure — logs and returns False so registration can
    still report success and the user can request a resend.
    """
    cfg = config if config is not None else load_smtp_config()
    if not cfg.configured:
        logger.warning(
            "SMTP not configured — activation link for %s: %s", to_email, activation_url
        )
        return False
    try:
        msg = _build_message(cfg, to_email, activation_url)
        with smtplib.SMTP(cfg.host, cfg.port, timeout=15) as smtp:
            if cfg.use_tls:
                smtp.starttls()
            if cfg.user:
                smtp.login(cfg.user, cfg.password)
            smtp.send_message(msg)
        return True
    except Exception as exc:  # noqa: BLE001 - mail failure must not break registration
        logger.error("Failed to send activation email to %s: %s", to_email, exc)
        return False


__all__ = ["SmtpConfig", "load_smtp_config", "send_activation_email"]
