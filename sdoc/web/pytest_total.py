"""Loaded into the live test run (pytest -p) to announce the total up front.

pytest -q prints nothing before the first result, so without this the page
could count tests but not say out of how many. The marker starts with a
capital S: a lowercase s is what pytest prints for a skipped test.
"""


def pytest_collection_finish(session):
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter:
        reporter.write_line(f"SDOC-TOTAL {len(session.items)}")
