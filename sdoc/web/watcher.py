"""Runs the mail watch inside the web process, so one deploy does both.

A background thread rather than an async task: the IMAP fetch and the Claude
calls are both blocking, and a thread keeps them off the event loop without
rewriting either. It is a daemon, so it never holds up a shutdown.

Off automatically when no mail credentials are set, which is what makes a
local run and the whole test suite behave as before.
"""
import logging
import os
import shutil
import threading
import traceback
from pathlib import Path

from sdoc.config import MAIL_DIR, OUT_DIR, ROOT
from sdoc.run_watch import poll_once

log = logging.getLogger(__name__)

INTERVAL = int(os.environ.get("SDOC_WATCH_INTERVAL", "20"))

# Results that ship with the code, copied onto a mounted volume the first
# time it is used. Without this, pointing SDOC_OUT at a fresh volume would
# show all 520 emails with no verdicts.
SEEDED = ("results.json", "categories.json", "submission.json")


def seed_output(out_dir: Path | None = None, shipped: Path | None = None) -> list[str]:
    """Copy shipped results into OUT_DIR if they are not there yet.

    Does nothing when OUT_DIR is the shipped folder itself, which is the
    normal local case. Never overwrites: a verdict already on the volume is
    newer than the one baked into the image.
    """
    out = Path(out_dir or OUT_DIR)
    src_dir = Path(shipped) if shipped is not None else Path(ROOT) / "out"
    if not src_dir.exists() or out.resolve() == src_dir.resolve():
        return []
    out.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in SEEDED:
        src, dst = src_dir / name, out / name
        if src.exists() and not dst.exists():
            shutil.copy2(src, dst)
            copied.append(name)
    if copied:
        log.info("seeded %s with %s", out, ", ".join(copied))
    return copied


def enabled() -> bool:
    """Off with SDOC_WATCH=0. On otherwise, if credentials resolve."""
    return os.environ.get("SDOC_WATCH", "1") != "0"


def _default_mailbox():
    from sdoc.mail.gmail import Mailbox      # imported late: needs credentials
    return Mailbox()


def _loop(stop: threading.Event, interval: int, mailbox_factory=None) -> None:
    try:
        mailbox = (mailbox_factory or _default_mailbox)()
    except Exception as e:
        log.info("mail watcher off - %s", e)
        return
    log.info("mail watcher on - %s, polling every %ss", getattr(mailbox, "user", "?"), interval)

    # wait() before the first poll, not after: startup stays instant, and a
    # container stuck in a restart loop cannot hammer the mail server.
    while not stop.wait(interval):
        try:
            poll_once(mailbox, root=MAIL_DIR, out_dir=OUT_DIR)
        except Exception:
            log.warning("poll failed, retrying next tick:\n%s", traceback.format_exc())


def start(interval: int | None = None, mailbox_factory=None):
    """Start the watch thread. Returns (thread, stop_event), or None if off."""
    if not enabled():
        log.info("mail watcher disabled (SDOC_WATCH=0)")
        return None
    stop = threading.Event()
    thread = threading.Thread(
        target=_loop, args=(stop, interval or INTERVAL, mailbox_factory),
        daemon=True, name="sdoc-mail-watch")
    thread.start()
    return thread, stop
