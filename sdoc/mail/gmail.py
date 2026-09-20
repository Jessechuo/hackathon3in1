"""Gmail over IMAP. The only file in the project that talks to a mail server.

Gmail needs an App Password, not the account password: turn on 2-Step
Verification, then create one at myaccount.google.com/apppasswords. Put both
values in .env or .env.txt - gitignored, and loaded by sdoc.config:

    SDOC_MAIL_USER=hackathon3in1@gmail.com
    SDOC_MAIL_PASSWORD=abcdefghijklmnop
"""
import imaplib
import logging
import os

# Importing config loads .env / .env.txt, so the credentials below resolve
# without anything having to be exported first.
import sdoc.config  # noqa: F401

log = logging.getLogger(__name__)

HOST = "imap.gmail.com"


class Mailbox:
    def __init__(self, user: str | None = None, password: str | None = None,
                 host: str = HOST):
        self.user = user or os.environ.get("SDOC_MAIL_USER")
        self.password = password or os.environ.get("SDOC_MAIL_PASSWORD")
        self.host = host
        if not self.user or not self.password:
            raise RuntimeError(
                "set SDOC_MAIL_USER and SDOC_MAIL_PASSWORD (a Gmail App Password, "
                "not the account password)")

    def fetch_unseen(self, limit: int = 20) -> list[bytes]:
        """Raw messages waiting in INBOX, marked read as they are taken.

        Marking read is what stops a message being processed - and billed -
        twice: the next poll no longer sees it.
        """
        raw: list[bytes] = []
        with imaplib.IMAP4_SSL(self.host) as M:
            M.login(self.user, self.password)
            M.select("INBOX")
            _, data = M.search(None, "UNSEEN")
            for num in (data[0].split() if data and data[0] else [])[:limit]:
                _, parts = M.fetch(num, "(RFC822)")
                for part in parts:
                    if isinstance(part, tuple) and part[1]:
                        raw.append(part[1])
                        break
                M.store(num, "+FLAGS", "\\Seen")
        return raw
