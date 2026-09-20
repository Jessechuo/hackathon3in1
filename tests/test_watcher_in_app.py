import threading

from fastapi.testclient import TestClient

from sdoc.web import app as web
from sdoc.web import watcher


class StubMailbox:
    user = "stub@example.org"

    def __init__(self):
        self.polls = threading.Event()

    def fetch_unseen(self, limit=20):
        self.polls.set()
        return []


def test_the_watcher_is_off_when_told_to_be(monkeypatch):
    monkeypatch.setenv("SDOC_WATCH", "0")
    assert watcher.enabled() is False
    assert watcher.start() is None


def test_the_watcher_is_on_by_default(monkeypatch):
    monkeypatch.delenv("SDOC_WATCH", raising=False)
    assert watcher.enabled() is True


def test_no_credentials_means_the_thread_exits_instead_of_crashing():
    """A local run without mail credentials must behave exactly as before."""
    def no_credentials():
        raise RuntimeError("set SDOC_MAIL_USER and SDOC_MAIL_PASSWORD")

    stop = threading.Event()
    watcher._loop(stop, interval=0.01, mailbox_factory=no_credentials)  # returns


def test_the_loop_polls_and_stops_when_asked(monkeypatch):
    box = StubMailbox()
    monkeypatch.setattr(watcher, "poll_once", lambda mailbox, root=None, out_dir=None:
                        mailbox.fetch_unseen())
    stop = threading.Event()
    t = threading.Thread(target=watcher._loop, args=(stop, 0.01, lambda: box), daemon=True)
    t.start()
    assert box.polls.wait(timeout=5), "the watcher never polled"
    stop.set()
    t.join(timeout=5)
    assert not t.is_alive()


def test_starting_the_app_does_not_poll_when_the_watcher_is_off(monkeypatch):
    """The whole suite relies on this: no test may reach a real mailbox."""
    monkeypatch.setenv("SDOC_WATCH", "0")
    started = []
    monkeypatch.setattr(watcher, "_loop", lambda *a, **k: started.append(True))
    with TestClient(web.app) as client:
        assert client.get("/").status_code == 200
    assert started == []


def test_a_fresh_volume_is_seeded_with_the_shipped_results(tmp_path):
    shipped, volume = tmp_path / "shipped", tmp_path / "volume"
    shipped.mkdir()
    (shipped / "results.json").write_text('{"email_001": {}}', encoding="utf-8")
    (shipped / "submission.json").write_text("{}", encoding="utf-8")

    copied = watcher.seed_output(out_dir=volume, shipped=shipped)

    assert sorted(copied) == ["results.json", "submission.json"]
    assert (volume / "results.json").read_text(encoding="utf-8") == '{"email_001": {}}'


def test_seeding_never_overwrites_what_is_already_on_the_volume(tmp_path):
    """A verdict on the volume is newer than the one baked into the image."""
    shipped, volume = tmp_path / "shipped", tmp_path / "volume"
    shipped.mkdir()
    volume.mkdir()
    (shipped / "results.json").write_text("SHIPPED", encoding="utf-8")
    (volume / "results.json").write_text("LIVE", encoding="utf-8")

    assert watcher.seed_output(out_dir=volume, shipped=shipped) == []
    assert (volume / "results.json").read_text(encoding="utf-8") == "LIVE"


def test_seeding_does_nothing_when_out_dir_is_the_shipped_folder(tmp_path):
    """The normal local case: no volume, so there is nothing to copy."""
    shipped = tmp_path / "out"
    shipped.mkdir()
    (shipped / "results.json").write_text("x", encoding="utf-8")
    assert watcher.seed_output(out_dir=shipped, shipped=shipped) == []
