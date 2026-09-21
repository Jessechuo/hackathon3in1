"""Run the Malay and Chinese demo emails through the real pipeline - the
same ingest() the mailbox watcher uses - and say whether each came out as
expected. Costs about 10 cents of API credit. Uses throwaway folders, so
nothing lands in the real mail/ or out/, and a fresh cache, so every
answer is a real call rather than a remembered one.

    python tools/multilang_check.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo" / "multilang"
SCRATCH = Path(tempfile.mkdtemp(prefix="mailops-multilang-"))
os.environ["SDOC_MAIL"] = str(SCRATCH / "mail")
os.environ["SDOC_OUT"] = str(SCRATCH / "out")
os.environ["SDOC_CACHE"] = str(SCRATCH / "cache")
sys.path.insert(0, str(ROOT))

from sdoc.ingest import ingest            # noqa: E402  (after the folders are set)
from sdoc.mail.store import save_email    # noqa: E402


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")      # Chinese on a Windows console
    cases = json.loads((DEMO / "cases.json").read_text(encoding="utf-8"))
    failures = 0
    for c in cases:
        files = [(n, (DEMO / n).read_bytes()) for n in c["attachments"]]
        body = (DEMO / c["body"]).read_text(encoding="utf-8")
        email = save_email(c["from"], c["subject"], body, files, root=SCRATCH / "mail")
        r = ingest(email, SCRATCH / "out")
        want = c["expect"]
        got_fields = sorted(r.get("defect_fields") or [])
        ok = (r["category"] == want["category"] and r["status"] == want["status"]
              and got_fields == sorted(want.get("defect_fields", [])))
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {c['id']:<18} {r['category']:<14} {r['status']:<12} "
              f"{','.join(got_fields) or '-':<16} {r.get('reason', '')}")
        if not ok and r.get("note"):
            print(f"      note: {r['note']}")
        for f in r.get("fields") or []:
            mark = {True: "=", False: "x", None: "?"}[f["match"]]
            print(f"   {mark}  {f['name']:<18} {str(f['si'])[:34]:<34} | {str(f['bl'])[:30]:<30}"
                  f" en: {f.get('si_en')} | {f.get('bl_en')}")
    print(f"\n{len(cases) - failures} of {len(cases)} as expected")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
