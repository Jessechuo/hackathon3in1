"""Watch a mailbox. Anything that arrives is classified and compared.

    python -m sdoc.run_watch --once        one pass, then stop
    python -m sdoc.run_watch               poll every 20 seconds
"""
import argparse
import logging
import time
import traceback
from pathlib import Path

from sdoc.ingest import ingest
from sdoc.mail.parse import parse_message
from sdoc.mail.store import save_email

log = logging.getLogger(__name__)

INTERVAL = 20


def poll_once(mailbox, root: Path | None = None, out_dir: Path | None = None) -> list[dict]:
    """Fetch, store and process whatever is waiting. Returns the results.

    A message that cannot even be parsed is logged and skipped rather than
    stopping the pass - it has already been marked read, so it will not come
    back, and the rest of the batch still gets through.
    """
    results = []
    for raw in mailbox.fetch_unseen():
        try:
            parsed = parse_message(raw)
        except Exception:
            log.warning("could not parse a message, skipping it:\n%s", traceback.format_exc())
            continue
        email = save_email(parsed["from"], parsed["subject"], parsed["body"],
                           parsed["attachments"], root=root)
        result = ingest(email, out_dir=out_dir)
        log.info("%s  %-14s %-12s %s", email["email_id"], result.get("category", "?"),
                 result.get("status", "?"), email["subject"][:60])
        results.append(result)
    return results


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    for noisy in ("httpx", "httpx2"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--once", action="store_true", help="one pass, then stop")
    ap.add_argument("--interval", type=int, default=INTERVAL,
                    help=f"seconds between polls (default {INTERVAL})")
    args = ap.parse_args()

    from sdoc.mail.gmail import Mailbox      # imported here so --help needs no credentials
    mailbox = Mailbox()
    log.info("watching %s - press Ctrl+C to stop", mailbox.user)

    while True:
        try:
            poll_once(mailbox)
        except Exception:
            # A dropped connection or a flaky network must not end the watch.
            log.warning("poll failed, retrying next tick:\n%s", traceback.format_exc())
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
