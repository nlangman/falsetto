"""Falsetto leaves pytest's own behavior intact, and its verdicts reach pytest's tools."""

from __future__ import annotations

import itertools
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import falsetto
import falsetto.plugin as plugin
from tests.helpers import (
    RUN,
    everything_is_proven,
    false_never_fails_the_build,
    line,
    markers_are_ignored,
)

XFAIL = """
import pytest

@pytest.mark.xfail(strict=True)
def test_strict_and_unexpectedly_passes():
    assert True

@pytest.mark.xfail
def test_unexpectedly_passes():
    assert True

@pytest.mark.xfail
def test_expected_to_fail():
    assert False
"""


def grade_xfail_too(m: falsetto.Patch) -> None:
    m.setattr(plugin, "_is_xfail", lambda report: False)


@falsetto.must_fail_when(grade_xfail_too)
def test_xfail_reports_are_left_to_pytest(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(XFAIL)
    stock = pytester.runpytest("-p", "no:cacheprovider", "-rA")
    graded = pytester.runpytest(*RUN, "-rA")
    assert "XPASS(strict)" in stock.stdout.str()
    assert "XPASS(strict)" in graded.stdout.str()
    assert "1 failed, 1 xfailed, 1 xpassed" in graded.stdout.str()
    assert "(1 graded of 3 run; 2 xfail)" in graded.stdout.str()
    assert graded.ret == stock.ret == 1


SKIPPED = """
import pytest
import falsetto

VALUE = {"key": "k1"}

@pytest.mark.skip(reason="not now")
def test_skipped():
    assert True

@falsetto.must_fail_when(lambda m: m.setitem(VALUE, "key", None))
def test_proven():
    assert VALUE["key"] == "k1"
"""


def skips_vanish_from_the_line(m: falsetto.Patch) -> None:
    original = plugin.Tally.statuses

    def without_skips(self: plugin.Tally) -> dict[str, int]:
        return {k: v for k, v in original(self).items() if k != "skipped"}

    m.setattr(plugin.Tally, "statuses", without_skips)


@falsetto.must_fail_when(skips_vanish_from_the_line)
def test_skips_are_counted_in_the_denominator(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(SKIPPED)
    result = pytester.runpytest(*RUN)
    assert line(1, 0, 0, 0) + " (1 graded of 2 run; 1 skipped)" in result.stdout.str()
    assert result.ret == 0


EXCLUDED = """
import pytest

@pytest.mark.no_proof("talks to a live service")
def test_live():
    assert True
"""


@falsetto.must_fail_when(markers_are_ignored)
def test_excluded_checks_are_listed_and_never_a_pass(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(EXCLUDED)
    result = pytester.runpytest(*RUN, "--falsetto-strict", "-v")
    out = result.stdout.str()
    assert "EXCLUDED test_excluded_checks_are_listed_and_never_a_pass.py::test_live: talks" in out
    assert "0 graded of 1 run; 1 excluded" in out
    assert "no check was graded" in out
    assert result.ret == 1


KEYWORD_REASON = """
import pytest

@pytest.mark.no_proof(reason="talks to a live service")
def test_live():
    assert True
"""


def only_a_positional_reason_counts(m: falsetto.Patch) -> None:
    """Falsifies "no_proof takes its reason as a keyword": only a positional one is read."""

    def marker_reason(item: pytest.Item) -> str | None:
        marker = item.get_closest_marker(plugin.MARKER)
        if marker is None:
            return None
        return str(marker.args[0] if marker.args else "").strip()

    m.setattr(plugin, "_marker_reason", marker_reason)


@falsetto.must_fail_when(only_a_positional_reason_counts)
def test_no_proof_takes_its_reason_as_a_keyword(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(KEYWORD_REASON)
    result = pytester.runpytest(*RUN)
    out = result.stdout.str()
    assert "::test_live: talks to a live service" in out
    assert "0 graded of 1 run; 1 excluded" in out
    assert result.ret == 0


NO_REASON = """
import pytest

@pytest.mark.no_proof
def test_live():
    assert True
"""


def any_marker_counts(m: falsetto.Patch) -> None:
    m.setattr(plugin, "_marker_reason", lambda item: "(no reason given)")


@falsetto.must_fail_when(any_marker_counts)
def test_no_proof_requires_a_reason(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(NO_REASON)
    result = pytester.runpytest(*RUN)
    out = result.stdout.str()
    assert line(0, 0, 0, 1) in out
    assert "carries no reason" in out


CONTRADICTION = """
import pytest
import falsetto

VALUE = {"key": "k1"}

@pytest.mark.no_proof("cannot be proven")
@falsetto.must_fail_when(lambda m: m.setitem(VALUE, "key", None))
def test_both():
    assert VALUE["key"] == "k1"
"""


@falsetto.must_fail_when(markers_are_ignored)
def test_no_proof_and_a_declaration_contradict(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(CONTRADICTION)
    result = pytester.runpytest(*RUN)
    out = result.stdout.str()
    assert line(0, 0, 0, 1) in out
    assert "contradict" in out


DOCTEST_AND_A_CHECK = '''
import falsetto

def double(n):
    """
    >>> double(2)
    4
    """
    return n * 2

@falsetto.must_fail_when(lambda m: m.setattr(__import__(__name__), "double", lambda n: 0))
def test_double():
    assert double(2) == 4
'''


def grade_every_item(m: falsetto.Patch) -> None:
    m.setattr(plugin, "_gradable", lambda item: True)


@falsetto.must_fail_when(grade_every_item)
def test_doctests_are_not_graded(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(DOCTEST_AND_A_CHECK)
    result = pytester.runpytest(*RUN, "--falsetto-strict", "--doctest-modules")
    out = result.stdout.str()
    assert "1 not gradable" in out
    assert "no check was graded" not in out
    assert result.ret == 0


FALSE_THEN_PROVEN = """
import falsetto

VALUE = {"key": "k1"}

@falsetto.must_fail_when(lambda m: m.setitem(VALUE, "key", "zzz"))
def test_a_false():
    expected = VALUE["key"]
    assert VALUE["key"] == expected

@falsetto.must_fail_when(lambda m: m.setitem(VALUE, "key", None))
def test_b_proven():
    assert VALUE["key"] == "k1"
"""


def verdicts_never_reach_a_report(m: falsetto.Patch) -> None:
    """Falsifies "a false verdict lands on the report pytest's own tools read"."""
    m.setattr(plugin, "_attach_target", lambda reports: None)


@falsetto.must_fail_when(verdicts_never_reach_a_report)
def test_stop_on_first_failure_stops_on_a_false_check(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(FALSE_THEN_PROVEN)
    result = pytester.runpytest(*RUN, "-x")
    out = result.stdout.str()
    assert "1 graded of 1 run" in out
    assert "stopping after 1 failures" in out


@falsetto.must_fail_when(verdicts_never_reach_a_report)
def test_last_failed_reruns_only_the_false_check(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(FALSE_THEN_PROVEN)
    pytester.runpytest("--falsetto")
    again = pytester.runpytest("--falsetto", "--lf")
    out = again.stdout.str()
    assert line(0, 0, 1, 0) + " (1 graded of 1 run)" in out
    assert "test_b_proven" not in out


@falsetto.must_fail_when(verdicts_never_reach_a_report)
def test_junit_counts_a_false_check_as_a_failure(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(FALSE_THEN_PROVEN)
    xml = pytester.path / "junit.xml"
    pytester.runpytest(*RUN, f"--junitxml={xml}")
    text = xml.read_text().replace("&quot;", '"')
    assert 'failures="1"' in text
    assert plugin.PROPERTY in text
    assert '"verdict": "false"' in text


def verdicts_vanish_in_the_controller(m: falsetto.Patch) -> None:
    m.setattr(plugin, "verdict_of", lambda report: None)


@falsetto.must_fail_when(verdicts_vanish_in_the_controller)
def test_verdicts_survive_xdist_workers(pytester: pytest.Pytester) -> None:
    pytest.importorskip("xdist")
    pytester.makepyfile(FALSE_THEN_PROVEN)
    result = pytester.runpytest(*RUN, "-n", "2")
    out = result.stdout.str()
    assert line(1, 0, 1, 0) + " (2 graded of 2 run)" in out
    assert result.ret == 1


def json_is_never_written(m: falsetto.Patch) -> None:
    m.setattr(plugin._Session, "write_json", lambda self, path, session: None)


@falsetto.must_fail_when(json_is_never_written)
def test_json_report_carries_every_verdict_and_creates_its_directory(
    pytester: pytest.Pytester,
) -> None:
    pytester.makepyfile(FALSE_THEN_PROVEN)
    path = pytester.path / "reports" / "nested" / "falsetto.json"
    pytester.runpytest(*RUN, f"--falsetto-json={path}")
    assert path.exists()
    payload = json.loads(path.read_text())
    assert payload["totals"]["verdicts"]["false"] == 1
    assert payload["totals"]["verdicts"]["proven"] == 1
    verdicts = {c["nodeid"].split("::")[-1]: c["verdict"] for c in payload["checks"]}
    assert verdicts == {"test_a_false": "false", "test_b_proven": "proven"}
    assert all("hint" in c and "reason" in c and "evidence" in c for c in payload["checks"])


CONTEXT_FIELDS = (
    "schema",
    "started",
    "finished",
    "rootdir",
    "args",
    "strict",
    "controls",
    "pytest",
    "python",
)


def the_report_records_no_run_context(m: falsetto.Patch) -> None:
    """Falsifies "the report says which run it came from": the context fields are not written."""
    original = plugin._Session.write_json

    def write_json(self: plugin._Session, path: Path, session: pytest.Session) -> None:
        original(self, path, session)
        kept = {k: v for k, v in json.loads(path.read_text()).items() if k not in CONTEXT_FIELDS}
        path.write_text(json.dumps(kept, indent=2))

    m.setattr(plugin._Session, "write_json", write_json)


@falsetto.must_fail_when(the_report_records_no_run_context)
def test_the_json_report_carries_the_run_it_came_from(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(FALSE_THEN_PROVEN)
    path = pytester.path / "falsetto.json"
    pytester.runpytest(*RUN, "--falsetto-strict", f"--falsetto-json={path}")
    payload = json.loads(path.read_text())
    assert payload.get("schema") == 1
    assert payload.get("strict") is True
    assert payload.get("controls") == 1
    assert payload.get("pytest") == pytest.__version__
    assert Path(str(payload.get("rootdir"))).resolve() == pytester.path.resolve()
    assert isinstance(payload.get("started"), str)
    assert isinstance(payload.get("finished"), str)


def the_run_clock_runs_backwards(m: falsetto.Patch) -> None:
    """Falsifies "the report's timestamps bracket the run": each reading is earlier."""
    real = plugin._now
    readings = itertools.count()

    def now() -> str:
        moment = datetime.fromisoformat(real()) - timedelta(seconds=next(readings))
        return moment.isoformat(timespec="seconds")

    m.setattr(plugin, "_now", now)


@falsetto.must_fail_when(the_run_clock_runs_backwards)
def test_the_json_reports_timestamps_bracket_the_run(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(FALSE_THEN_PROVEN)
    path = pytester.path / "falsetto.json"
    pytester.runpytest(*RUN, f"--falsetto-json={path}")
    payload = json.loads(path.read_text())
    started = datetime.fromisoformat(payload["started"])
    finished = datetime.fromisoformat(payload["finished"])
    assert started <= finished


FALSE_PROVEN_AND_UNDECLARED = """
import falsetto

VALUE = {"key": "k1"}

@falsetto.must_fail_when(lambda m: m.setitem(VALUE, "key", "zzz"))
def test_a_false():
    expected = VALUE["key"]
    assert VALUE["key"] == expected

@falsetto.must_fail_when(lambda m: m.setitem(VALUE, "key", None))
def test_b_proven():
    assert VALUE["key"] == "k1"

def test_c_undeclared():
    assert VALUE["key"] == "k1"
"""


@falsetto.must_fail_when(false_never_fails_the_build)
def test_each_record_says_whether_its_verdict_fails_the_build(
    pytester: pytest.Pytester,
) -> None:
    pytester.makepyfile(FALSE_PROVEN_AND_UNDECLARED)
    path = pytester.path / "falsetto.json"
    pytester.runpytest(*RUN, "--falsetto-strict", f"--falsetto-json={path}")
    payload = json.loads(path.read_text())
    flags = {c["nodeid"].split("::")[-1]: c["fails_build"] for c in payload["checks"]}
    assert flags == {"test_a_false": True, "test_b_proven": False, "test_c_undeclared": True}
    totals = payload["totals"]
    assert set(totals["verdicts"]) == {"proven", "failed", "false", "unproven"}
    assert not set(totals["statuses"]) & set(totals["verdicts"])


def setup_only_is_a_real_run(m: falsetto.Patch) -> None:
    m.setattr(plugin, "_runs_nothing", lambda config: False)


@falsetto.must_fail_when(setup_only_is_a_real_run)
def test_setup_only_is_not_graded_and_strict_stays_green(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(FALSE_THEN_PROVEN)
    result = pytester.runpytest(*RUN, "--falsetto-strict", "--setup-only")
    assert result.ret == 0
    assert "no check was graded" not in result.stdout.str()


COMPETING_CONFTEST = """
def pytest_runtest_protocol(item, nextitem):
    return None
"""


def the_warning_names_nobody(m: falsetto.Patch) -> None:
    """Falsifies "the warning names the plugin Falsetto competes with"."""

    def warn(config: pytest.Config) -> None:
        config.issue_config_time_warning(
            pytest.PytestWarning(
                "falsetto and another plugin both take over the test protocol, and "
                "whichever pytest calls first wins for each check. Checks they run are "
                "reported as not graded, never as a pass."
            ),
            stacklevel=2,
        )

    m.setattr(plugin, "_warn_competing_protocols", warn)


@falsetto.must_fail_when(the_warning_names_nobody)
def test_a_competing_protocol_plugin_is_named_in_a_warning(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(COMPETING_CONFTEST)
    pytester.makepyfile(FALSE_THEN_PROVEN)
    result = pytester.runpytest(*RUN)
    out = result.stdout.str()
    assert "both take over the test protocol" in out
    # The warning prints the plugin's path inside a list, so on Windows its backslashes
    # are doubled; the directory's name and the file's name are what a reader needs.
    assert pytester.path.name in out
    assert "conftest.py" in out


STATS_CONFTEST = """
def pytest_terminal_summary(terminalreporter):
    print("PASSED_COUNT", len(terminalreporter.stats.get("passed", [])))
"""

PROVEN_ONLY = """
import falsetto

VALUE = {"key": "k1"}

@falsetto.must_fail_when(lambda m: m.setitem(VALUE, "key", None))
def test_proven():
    assert VALUE["key"] == "k1"
"""


def proven_is_its_own_category(m: falsetto.Patch) -> None:
    m.setattr(plugin, "_status_for", lambda info, report: ("proven", ".", "PROVEN"))


@falsetto.must_fail_when(proven_is_its_own_category)
def test_proven_checks_still_count_as_passed_for_other_reporters(
    pytester: pytest.Pytester,
) -> None:
    pytester.makeconftest(STATS_CONFTEST)
    pytester.makepyfile(PROVEN_ONLY)
    result = pytester.runpytest(*RUN, "-s")
    assert "PASSED_COUNT 1" in result.stdout.str()


@falsetto.must_fail_when(everything_is_proven)
def test_the_router_example_line_is_what_the_readme_promises(pytester: pytest.Pytester) -> None:
    """A summary-shaped check: it uses the chokepoint, since every count moves together."""
    example = Path(__file__).resolve().parent.parent / "examples" / "router"
    result = pytester.runpytest(str(example), *RUN)
    assert line(1, 1, 1, 1) + " (4 graded of 4 run)" in result.stdout.str()
    assert result.ret == 1


EXITS_ON_RERUN = """
import falsetto
import pytest

RUNS = {"n": 0}
VALUE = {"key": "k1"}

@falsetto.must_fail_when(lambda m: m.setitem(VALUE, "key", None))
def test_exits_when_it_is_run_again():
    RUNS["n"] += 1
    if RUNS["n"] > 1:
        pytest.exit("stop")
    assert VALUE["key"] == "k1"
"""


def exits_are_caught_and_graded(m: falsetto.Patch) -> None:
    """Falsifies "pytest.exit out of a graded run ends the session": it is graded instead."""
    m.setattr(plugin, "PASSTHROUGH", (KeyboardInterrupt, SystemExit))


@falsetto.must_fail_when(exits_are_caught_and_graded)
def test_pytest_exit_from_a_graded_run_ends_the_session(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(EXITS_ON_RERUN)
    result = pytester.runpytest(*RUN)
    out = result.stdout.str()
    assert result.ret == pytest.ExitCode.INTERRUPTED
    assert "stop" in out
    assert "falsetto:" not in out
