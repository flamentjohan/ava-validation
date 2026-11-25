"""Envoi des mails de validation : SMTP réel si configuré, journal local sinon."""
import os
import smtplib
from email.message import EmailMessage


def _smtp_config():
    host = os.environ.get("AVA_SMTP_HOST")
    if not host:
        return None
    return {
        "host": host,
        "port": int(os.environ.get("AVA_SMTP_PORT", "587")),
        "user": os.environ.get("AVA_SMTP_USER", ""),
        "password": os.environ.get("AVA_SMTP_PASSWORD", ""),
        "use_tls": os.environ.get("AVA_SMTP_TLS", "1") == "1",
        "sender": os.environ.get("AVA_SMTP_SENDER",
                                 os.environ.get("AVA_SMTP_USER",
                                                "no-reply@ava.local")),
    }


def _send(recipient, subject, body):
    cfg = _smtp_config()
    if cfg is None:
        return None, "SMTP non configuré (mail journalisé uniquement)"
    msg = EmailMessage()
    msg["From"] = cfg["sender"]
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=15) as smtp:
            if cfg["use_tls"]:
                smtp.starttls()
            if cfg["user"]:
                smtp.login(cfg["user"], cfg["password"])
            smtp.send_message(msg)
    except Exception as exc:
        return None, str(exc)
    return None, None


def send_validation_email(recipient, body, link):
    """Mail « Vous avez un projet AVA à valider » + lien vers la page."""
    subject = "Vous avez un projet AVA à valider"
    body_with_link = (body if link in body else
                      f"{body}\n\nLien vers la page de validation : {link}")
    _, error = _send(recipient, subject, body_with_link)
    return error


def send_final_confirmation(recipient, body):
    subject = "Votre projet AVA est validé"
    _, error = _send(recipient, subject, body)
    return error
