"""Falsetto leaves pytest's own behavior intact, and its verdicts reach pytest's tools."""

from __future__ import annotations

import json

import pytest

import falsetto
import falsetto.plugin as plugin
from tests.helpers import RUN, false_never_fails_the_build

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
    out = result.stdout.str()
    assert "1 proven, 0 failed, 0 false, 0 unproven (1 graded of 2 run; 1 skipped)" in out
    assert result.ret == 0


EXCLUDED = """
import pytest

@pytest.mark.no_proof("talks to a live service")
def test_live():
    assert True
"""


def exclusions_look_proven(m: falsetto.Patch) -> None:
    m.setattr(plugin, "MARKER", "some_other_marker")


@falsetto.must_fail_when(exclusions_look_proven)
def test_excluded_checks_are_visible_and_never_a_pass(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(EXCLUDED)
    result = pytester.runpytest(*RUN, "--falsetto-strict")
    out = result.stdout.str()
    assert "0 graded of 1 run; 1 excluded" in out
    assert "no check was graded" in out
    assert result.ret == 1


DOCTEST_MODULE = '''
def double(n):
    """
    >>> double(2)
    4
    """
    return n * 2

import falsetto

@falsetto.must_fail_when(lambda m: m.setattr(__import__(__name__), "double", lambda n: 0))
def test_double():
    assert double(2) == 4
'''


def grade_every_item(m: falsetto.Patch) -> None:
    m.setattr(plugin, "_gradable", lambda item: True)


@falsetto.must_fail_when(grade_every_item)
def test_doctests_are_not_graded_and_strict_stays_satisfiable(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(DOCTEST_MODULE)
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


@falsetto.must_fail_when(false_never_fails_the_build)
def test_stop_on_first_failure_stops_on_a_false_check(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(FALSE_THEN_PROVEN)
    result = pytester.runpytest(*RUN, "-x")
    out = result.stdout.str()
    assert "1 graded of 1 run" in out
    assert "stopping after 1 failures" in out


@falsetto.must_fail_when(false_never_fails_the_build)
def test_last_failed_reruns_only_the_false_check(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(FALSE_THEN_PROVEN)
    pytester.runpytest("--falsetto")
    again = pytester.runpytest("--falsetto", "--lf")
    out = again.stdout.str()
    assert "0 proven, 0 failed, 1 false, 0 unproven (1 graded of 1 run)" in out
    assert "test_b_proven" not in out


@falsetto.must_fail_when(false_never_fails_the_build)
def test_junit_counts_a_false_check_as_a_failure(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(FALSE_THEN_PROVEN)
    xml = pytester.path / "junit.xml"
    pytester.runpytest(*RUN, f"--junitxml={xml}")
    text = xml.read_text()
    assert 'failures="1"' in text
    assert '"verdict": "false"' in text.replace("&quot;", '"')


def verdicts_vanish_in_the_controller(m: falsetto.Patch) -> None:
    m.setattr(plugin, "verdict_of", lambda report: None)


@falsetto.must_fail_when(verdicts_vanish_in_the_controller)
def test_verdicts_survive_xdist_workers(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(FALSE_THEN_PROVEN)
    result = pytester.runpytest(*RUN, "-n", "2")
    out = result.stdout.str()
    assert "1 proven, 0 failed, 1 false, 0 unproven (2 graded of 2 run)" in out
    assert result.ret == 1


def json_is_never_written(m: falsetto.Patch) -> None:
    m.setattr(plugin._Session, "write_json", lambda self, path: None)


@falsetto.must_fail_when(json_is_never_written)
def test_json_report_carries_every_verdict(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(FALSE_THEN_PROVEN)
    path = pytester.path / "falsetto.json"
    pytester.runpytest(*RUN, f"--falsetto-json={path}")
    assert path.exists()
    payload = json.loads(path.read_text())
    assert payload["totals"]["false"] == 1
    assert payload["totals"]["proven"] == 1
    verdicts = {c["nodeid"].split("::")[-1]: c["verdict"] for c in payload["checks"]}
    assert verdicts == {"test_a_false": "false", "test_b_proven": "proven"}
    assert all("hint" in c and "reason" in c for c in payload["checks"])


def summarize_even_when_nothing_ran(m: falsetto.Patch) -> None:
    m.setattr(plugin.Tally, "run", property(lambda self: max(1, len(self.items))))


@falsetto.must_fail_when(summarize_even_when_nothing_ran)
def test_collect_only_prints_no_verdicts(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(FALSE_THEN_PROVEN)
    result = pytester.runpytest(*RUN, "--collect-only")
    assert "falsetto:" not in result.stdout.str()
