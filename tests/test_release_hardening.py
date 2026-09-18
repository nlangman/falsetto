"""Release hardening: a run nobody asked to grade, an interrupted revert, and unbounded text.

Each check here names one way a change reaches somewhere it was never meant to: a malformed
ini value into a plain pytest run, an interrupt out of a half-finished revert, an author's
string into a report.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Callable
from typing import Any

import pytest

import falsetto
import falsetto.core as core
import falsetto.declaration as declaration
import falsetto.patching as patching
import falsetto.plugin as plugin
from falsetto import Declaration, Patch, Reason, Verdict
from tests.helpers import RUN, line

BAD_CONTROLS_INI = "[pytest]\nfalsetto_controls = abc\n"

PLAIN = """
def test_plain():
    assert 1 + 1 == 2
"""


def the_enabled_gate_is_ignored(m: Patch) -> None:
    """Falsifies "a run that did not enable Falsetto never reads falsetto_controls"."""
    real = plugin._controls
    m.setattr(plugin, "_controls", lambda config, enabled: real(config, True))


@falsetto.must_fail_when(the_enabled_gate_is_ignored)
def test_a_malformed_controls_value_does_not_touch_an_ungraded_run(
    pytester: pytest.Pytester,
) -> None:
    pytester.makeini(BAD_CONTROLS_INI)
    pytester.makepyfile(PLAIN)
    result = pytester.runpytest("-p", "no:cacheprovider")
    assert "1 passed" in result.stdout.str()
    assert result.ret == 0


def a_bad_controls_value_raises_plainly(m: Patch) -> None:
    """Falsifies "a malformed falsetto_controls is a usage error, not a crash"."""

    def controls(config: pytest.Config, enabled: bool) -> int:
        return max(1, int(config.getini("falsetto_controls") or 1)) if enabled else 1

    m.setattr(plugin, "_controls", controls)


@falsetto.must_fail_when(a_bad_controls_value_raises_plainly)
def test_a_malformed_controls_value_is_a_usage_error_when_grading(
    pytester: pytest.Pytester,
) -> None:
    pytester.makeini(BAD_CONTROLS_INI)
    pytester.makepyfile(PLAIN)
    result = pytester.runpytest(*RUN)
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert "falsetto_controls must be an integer" in result.stderr.str()


def only_ordinary_errors_are_survivable(m: Patch) -> None:
    """Falsifies "an interrupt in one undo step still leaves every other step run"."""

    def attempt(step: Callable[[], None]) -> BaseException | None:
        try:
            step()
        except Exception as e:
            return e
        return None

    m.setattr(patching, "_attempt", attempt)


@falsetto.must_fail_when(only_ordinary_errors_are_survivable)
def test_an_interrupted_undo_step_does_not_strand_the_others() -> None:
    class Hostile:
        def __init__(self) -> None:
            object.__setattr__(self, "value", "original")

        def __setattr__(self, name: str, value: object) -> None:
            if value == "original":
                raise KeyboardInterrupt("interrupted while reverting")
            object.__setattr__(self, name, value)

    calm = {"key": "original"}
    hostile = Hostile()

    patch = Patch()
    patch.setitem(calm, "key", "changed")
    patch.setattr(hostile, "value", "changed")

    with pytest.raises(KeyboardInterrupt):
        patch.undo()
    assert calm["key"] == "original"


class _DropsTheContextPatch(Patch):
    """A handle whose undo raises the interrupt with nothing chained onto it."""

    def undo(self) -> None:
        try:
            super().undo()
        except BaseException as e:
            e.__context__ = None
            raise


PatchUnderTest: type[Patch] = Patch


def the_interrupt_is_raised_alone(m: Patch) -> None:
    """Falsifies "an interrupt carries the ordinary error another step raised as its context"."""
    import tests.test_release_hardening as here

    m.setattr(here, "PatchUnderTest", _DropsTheContextPatch)


@falsetto.must_fail_when(the_interrupt_is_raised_alone)
def test_an_interrupted_undo_carries_the_other_steps_error_as_its_context() -> None:
    class Hostile:
        def __init__(self) -> None:
            object.__setattr__(self, "value", "original")

        def __setattr__(self, name: str, value: object) -> None:
            if value == "original":
                raise KeyboardInterrupt("interrupted while reverting")
            object.__setattr__(self, name, value)

    hostile = Hostile()

    patch = PatchUnderTest()
    patch._undo.append(lambda: (_ for _ in ()).throw(RuntimeError("an undo step failed")))
    patch.setattr(hostile, "value", "changed")

    with pytest.raises(KeyboardInterrupt) as caught:
        patch.undo()
    assert isinstance(caught.value.__context__, RuntimeError)
    assert str(caught.value.__context__) == "an undo step failed"


def the_description_is_verbatim(m: Patch) -> None:
    """Falsifies "a declaration's description is bounded before it reaches a report"."""
    m.setattr(
        Declaration,
        "description",
        property(lambda self: self.describe or declaration._describe_callable(self.change)),
    )


@falsetto.must_fail_when(the_description_is_verbatim)
def test_a_huge_describe_is_clamped() -> None:
    decl = Declaration(change=lambda m: None, describe="x" * 100_000, scope="module")
    assert decl.description.startswith("xxx")
    assert decl.description.endswith(" [scope=module]")
    assert len(decl.description) <= declaration.TEXT_LIMIT + len(" [scope=module]")


def the_expectation_is_verbatim(m: Patch) -> None:
    """Falsifies "a predicate's repr is bounded before it reaches a report"."""
    m.setattr(
        Declaration,
        "expectation",
        property(lambda self: f"predicate {self.expect!r}"),
    )


@falsetto.must_fail_when(the_expectation_is_verbatim)
def test_a_huge_predicate_repr_is_clamped() -> None:
    class Huge:
        def __call__(self, exc: BaseException) -> bool:
            return True

        def __repr__(self) -> str:
            return "r" * 100_000

    decl = Declaration(change=lambda m: None, expect=Huge(), describe="a change")
    assert decl.expectation.startswith("predicate rrr")
    assert len(decl.expectation) <= declaration.TEXT_LIMIT
    assert decl.description.startswith("a change [expect=predicate rrr")
    assert len(decl.description) <= len("a change [expect=]") + declaration.TEXT_LIMIT


def evidence_is_unbounded(m: Patch) -> None:
    """Falsifies "an internal error's traceback is evidence, and evidence is bounded"."""
    m.setattr(core, "evidence", lambda text: text)


@falsetto.must_fail_when(evidence_is_unbounded)
def test_an_internal_errors_traceback_is_bounded() -> None:
    try:
        raise RuntimeError("x" * (core.EVIDENCE_LIMIT * 3))
    except RuntimeError as e:
        result = core.internal_error(e, None)

    assert result.detail is not None
    assert result.detail.startswith("RuntimeError: xxx")
    assert result.evidence is not None
    assert len(result.evidence) <= core.EVIDENCE_LIMIT


NOT_REVERTABLE = """
import falsetto


class Hostile:
    def __init__(self):
        object.__setattr__(self, "value", "original")

    def __setattr__(self, name, value):
        if value == "original":
            raise RuntimeError("the original value is not accepted back")
        object.__setattr__(self, name, value)


SUBJECT = Hostile()


@falsetto.must_fail_when(lambda m: m.setattr(SUBJECT, "value", "changed"))
def test_first():
    assert SUBJECT.value == "original"


def test_second():
    assert SUBJECT.value == "original"
"""


def the_session_runs_on(m: Patch) -> None:
    """Falsifies "a change that stayed applied stops the session before the next check"."""
    m.setattr(plugin, "_stop_if_not_reverted", lambda item, result: None)


@falsetto.must_fail_when(the_session_runs_on)
def test_a_change_that_stayed_applied_stops_the_session(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(NOT_REVERTABLE)
    result = pytester.runpytest(*RUN)
    out = result.stdout.str()
    assert line(0, 0, 0, 1) in out
    assert "(1 graded of 1 run)" in out
    assert "UNPROVEN (not-reverted)" in out
    assert "may still be applied to every later check" in out
    assert "a declared change could not be undone" in out
    assert "test_second" not in out
    assert result.ret == 1


def undo_failures_are_swallowed(m: Patch) -> None:
    """Falsifies "a change whose undo raises is graded not-reverted"."""

    def attempt(step: Callable[[], None]) -> BaseException | None:
        with contextlib.suppress(Exception):
            step()
        return None

    m.setattr(patching, "_attempt", attempt)


@falsetto.must_fail_when(undo_failures_are_swallowed)
def test_an_undo_that_raises_is_its_own_verdict_not_an_internal_error() -> None:
    class Hostile:
        value: str

        def __init__(self) -> None:
            object.__setattr__(self, "value", "original")

        def __setattr__(self, name: str, value: object) -> None:
            if value == "original":
                raise RuntimeError("the original value is not accepted back")
            object.__setattr__(self, name, value)

    subject = Hostile()

    def cell() -> None:
        assert subject.value == "original"

    decl = Declaration(
        change=lambda m: m.setattr(subject, "value", "changed"), describe="the value changed"
    )
    result = core.check_callable(cell, decl)

    assert result.verdict is Verdict.UNPROVEN
    assert result.reason is Reason.NOT_REVERTED
    assert result.detail is not None
    assert "RuntimeError: the original value is not accepted back" in result.detail
    assert result.evidence is not None


class Unusual(BaseException):
    """A BaseException outside the passthrough set: neither an interrupt nor an ordinary error."""


def only_ordinary_undo_failures_are_a_verdict(m: Patch) -> None:
    """Falsifies "an undo raising any non-passthrough BaseException is the not-reverted verdict".

    The narrower ``except Exception`` is restored, so an unusual one escapes ``prove`` instead
    of becoming the verdict that stops the session. That escape is the failure ``expect=`` names.
    """

    def revert(patch: Patch, declared: str | None, passthrough: core.Passthrough) -> Any:
        try:
            patch.undo()
        except passthrough:
            raise
        except Exception as e:
            detail = core.describe_exception(e)
            return falsetto.Result(Verdict.UNPROVEN, Reason.NOT_REVERTED, declared, detail)
        return None

    m.setattr(core, "_revert", revert)


@falsetto.must_fail_when(only_ordinary_undo_failures_are_a_verdict, expect=Unusual)
def test_an_undo_that_raises_an_unusual_base_exception_is_its_own_verdict() -> None:
    class Hostile:
        value: str

        def __init__(self) -> None:
            object.__setattr__(self, "value", "original")

        def __setattr__(self, name: str, value: object) -> None:
            if value == "original":
                raise Unusual("the original value is not accepted back")
            object.__setattr__(self, name, value)

    subject = Hostile()

    def cell() -> None:
        assert subject.value == "original"

    decl = Declaration(
        change=lambda m: m.setattr(subject, "value", "changed"), describe="the value changed"
    )
    result = core.check_callable(cell, decl)

    assert result.verdict is Verdict.UNPROVEN
    assert result.reason is Reason.NOT_REVERTED
    assert result.detail is not None
    assert "Unusual: the original value is not accepted back" in result.detail


CHANGE_THAT_RAISES = """
import falsetto


def explode(m):
    raise RuntimeError("the change itself failed")


@falsetto.must_fail_when(explode)
def test_change_cannot_apply():
    assert 1 + 1 == 2
"""


def locations_are_absolute(m: Patch) -> None:
    """Falsifies "a location inside the working directory is reported relative to it"."""
    m.setattr(core, "report_path", lambda filename: filename)


@falsetto.must_fail_when(locations_are_absolute)
def test_a_location_inside_the_working_directory_is_relative(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(test_location=CHANGE_THAT_RAISES)
    report = pytester.path / "falsetto.json"
    pytester.runpytest(*RUN, f"--falsetto-json={report}")
    record = json.loads(report.read_text())["checks"][0]

    assert record["reason"] == "not-applied"
    where = str(record["detail"]).split("; ")[-1]
    assert where.startswith("test_location.py:")


FORGED_VERDICT = """
import pytest


@pytest.mark.no_proof("talks to a live service")
def test_excluded(record_property):
    record_property("falsetto.verdict", '{"verdict": "bogus", "reason": "stated-reason"}')
"""


def records_are_taken_at_face_value(m: Patch) -> None:
    """Falsifies "a record that is not a verdict Falsetto could have written is ignored"."""

    def unvalidated(report: pytest.TestReport) -> dict[str, Any] | None:
        if report.when not in ("call", "teardown"):
            return None
        value = plugin._last_property(report, plugin.PROPERTY)
        if not isinstance(value, str):
            return None
        try:
            loaded = json.loads(value)
        except ValueError:
            return None
        if isinstance(loaded, dict) and "verdict" in loaded and "reason" in loaded:
            return loaded
        return None

    m.setattr(plugin, "verdict_of", unvalidated)


@falsetto.must_fail_when(records_are_taken_at_face_value)
def test_a_verdict_a_check_wrote_for_itself_is_not_a_verdict(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(FORGED_VERDICT)
    result = pytester.runpytest(*RUN)
    out = result.stdout.str()
    assert "INTERNALERROR" not in out
    assert line(0, 0, 0, 0) in out
    assert "(0 graded of 1 run; 1 excluded)" in out
    assert result.ret == 0


NOT_REPEATABLE = """
import falsetto

CALLS = []


@falsetto.must_fail_when(lambda m: None)
def test_counts_itself():
    CALLS.append(1)
    assert len(CALLS) == 1
"""


def the_front_end_slices_for_itself(m: Patch) -> None:
    """Falsifies "the plugin's evidence honours an empty limit": a zero slice keeps it all."""
    m.setattr(plugin, "_text", lambda report: report.longreprtext[-core.EVIDENCE_LIMIT :])


@falsetto.must_fail_when(the_front_end_slices_for_itself)
def test_an_empty_evidence_limit_keeps_no_evidence(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(NOT_REPEATABLE)
    report = pytester.path / "falsetto.json"
    with Patch() as patch:
        patch.setattr(core, "EVIDENCE_LIMIT", 0)
        pytester.runpytest(*RUN, f"--falsetto-json={report}")
    record = json.loads(report.read_text())["checks"][0]

    assert record["reason"] == "not-repeatable"
    assert record["evidence"] == ""


BROKEN_FIXTURE_MANAGER = """
import sys

import _pytest.fixtures

_original = _pytest.fixtures.FixtureManager.getfixturedefs


def _refuse_falsetto(self, argname, node):
    if sys._getframe(1).f_code.co_name == "_wider_fixtures":
        raise RuntimeError("the fixture manager could not be asked")
    return _original(self, argname, node)


def pytest_configure(config):
    _pytest.fixtures.FixtureManager.getfixturedefs = _refuse_falsetto


def pytest_unconfigure(config):
    _pytest.fixtures.FixtureManager.getfixturedefs = _original
"""

DYNAMIC_WIDER_FIXTURE = """
import falsetto
import pytest

CONFIG = {"prefix": "id-"}


@pytest.fixture(scope="module")
def ident():
    return CONFIG["prefix"] + "42"


@falsetto.must_fail_when(lambda m: m.setitem(CONFIG, "prefix", "BROKEN-"))
def test_reads_a_module_fixture_dynamically(request):
    assert request.getfixturevalue("ident").startswith("id-")
"""


def the_fixture_lookup_swallows_its_failure(m: Patch) -> None:
    """Falsifies "a fixture Falsetto could not look up is an error, never a false verdict"."""
    real = plugin._wider_fixtures

    def wider(item: pytest.Item, scope: str) -> list[str]:
        with contextlib.suppress(Exception):
            return real(item, scope)
        return []

    m.setattr(plugin, "_wider_fixtures", wider)


@falsetto.must_fail_when(the_fixture_lookup_swallows_its_failure)
def test_a_fixture_lookup_that_fails_is_not_a_false_verdict(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(BROKEN_FIXTURE_MANAGER)
    pytester.makepyfile(DYNAMIC_WIDER_FIXTURE)
    result = pytester.runpytest(*RUN)
    out = result.stdout.str()

    assert "FALSETTO-ERROR" in out
    assert "the fixture manager could not be asked" in out
    assert "FALSE" not in out.replace("FALSETTO-ERROR", "")
    assert line(0, 0, 0, 1) in out
    assert result.ret == 1
