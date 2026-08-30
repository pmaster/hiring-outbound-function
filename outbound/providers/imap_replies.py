"""IMAP as a replies source.

The default. Reads the sending mailbox directly, which is right when the
mailboxes are yours and you send over SMTP.
"""

from __future__ import annotations

from typing import Any

from . import register


class ImapReplies:
    name = "imap"

    def __init__(self, settings: Any):
        self.settings = settings
        cfg = (settings.get("providers.imap", {}) or {}) if hasattr(settings, "get") else {}
        self.folders = tuple(cfg.get("folders") or ("INBOX",))

    def fetch_replies(self, since: str | None = None) -> list[dict[str, Any]]:
        from ..replies import fetch_imap

        return [
            {
                "from_address": item.from_address,
                "subject": item.subject,
                "body": item.body,
                "date": item.date,
            }
            for item in fetch_imap(since=since, folders=self.folders)
        ]


register("replies", "imap")(ImapReplies)
