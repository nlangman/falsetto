"""The router example must print the verdict line the README promises."""

from pathlib import Path

import falsetto
from tests.test_plugin import stub_prove_all_proven

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "router"


@falsetto.must_fail_when(stub_prove_all_proven)
def test_router_example_prints_the_promised_line(pytester):
    result = pytester.runpytest(str(EXAMPLE), "-p", "no:cacheprovider")
    assert "falsetto: 1 proven, 1 failed, 1 false, 1 unproven" in result.stdout.str()
    assert result.ret == 1
