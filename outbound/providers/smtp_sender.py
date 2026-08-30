"""Plain SMTP. Send directly from the recruiting mailbox.

This is the right choice for the founder sent seats: 15 to 20 a day from one
mailbox, plain text, no tracking pixel, no sequencer footer. Deliverability
comes from the low volume and the fact that a person wrote the email.

Environment:

    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD
"""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, parseaddr
from typing import Any

from ..config import secret
from ..errors import ProviderError
from . import register


class SmtpSend:
    name = "smtp"

    def __init__(self, settings: Any):
        self.settings = settings
        self.host = secret("SMTP_HOST", required=True)
        self.port = int(secret("SMTP_PORT") or 587)
        self.user = secret("SMTP_USER", required=True)
        self.password = secret("SMTP_PASSWORD", required=True)

    def send(self, message: dict[str, Any]) -> str:
        mail = EmailMessage()
        name, address = parseaddr(str(message.get("from") or self.user))
        mail["From"] = formataddr((name, address or self.user))
        mail["To"] = message["to"]
        if message.get("reply_to"):
            mail["Reply-To"] = message["reply_to"]
        mail["Subject"] = message["subject"]
        message_id = make_msgid(domain=(address or self.user).split("@")[-1])
        mail["Message-ID"] = message_id
        # Plain text only. An HTML part is what makes a founder email look bulk.
        mail.set_content(message["body"])
        try:
            context = ssl.create_default_context()
            if self.port == 465:
                with smtplib.SMTP_SSL(self.host, self.port, context=context, timeout=30) as server:
                    server.login(self.user, self.password)
                    server.send_message(mail)
            else:
                with smtplib.SMTP(self.host, self.port, timeout=30) as server:
                    server.starttls(context=context)
                    server.login(self.user, self.password)
                    server.send_message(mail)
        except smtplib.SMTPException as exc:
            raise ProviderError(f"SMTP send failed: {exc}") from exc
        return message_id


register("send", "smtp")(SmtpSend)
