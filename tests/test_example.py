"""The router example must print the verdict line the README promises."""

from __future__ import annotations

from pathlib import Path

import pytest

import falsetto
from tests.helpers import everything_is_proven

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "router"


@falsetto.must_fail_when(everything_is_proven)
def test_router_example_prints_the_promised_line(pytester: pytest.Pytester) -> None:
    result = pytester.runpytest(str(EXAMPLE), "-p", "no:cacheprovider", "--falsetto")
    assert (
        "falsetto: 1 proven, 1 failed, 1 false, 1 unproven (4 graded of 4 run)"
        in result.stdout.str()
    )
    assert result.ret == 1
