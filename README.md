# Falsetto

**Green means nothing until it can go red.**

Falsetto is a test runner that refuses to count a check unless it can prove the check is capable of failing. Agents write tests faster than anyone reads them. Falsetto runs each one twice, once as written and once with the bug it claims to catch, and only counts the ones that fail when they should.

Test runners report two states: pass and fail. They hide a third: a test that cannot fail. It stays green because the thing it checks is missing on both sides, or the fixture is empty, or the assertion compares nothing to nothing. Such a test proves nothing, and it looks exactly like a test that proves everything. A falsetto is a voice that sounds high but is not the real voice. Falsetto finds the false voice in your suite, and screams.

## The problem, in one example

A message router copies a thread key from the incoming message onto the outgoing route.

```python
import falsetto
import router


def pick_route_dropping_thread_key(msg):
    route = original_pick_route(msg)
    return router.Route(thread_key=None, queue=route.queue)


@falsetto.must_fail_when(lambda m: m.setattr(router, "pick_route", pick_route_dropping_thread_key))
def test_route_keeps_thread_key(msg):
    route = router.pick_route(msg)
    assert route.thread_key == msg.thread_key
```

The declaration answers one question: what change should make this red? Here it is "the router drops the thread key", written as a small hand-made broken version of the function. Falsetto runs the test under that change, the assertion trips, and the test is **proven**.

A month later a colleague simplifies the shared fixture in another file, so `msg.thread_key` now defaults to `None`. Every test still passes. This one now asserts `None == None`. Under the declared change it still passes, because a dropped key is also `None`. Falsetto reports it **false** on that pull request, and the build fails. Nobody touched the test. Every other runner said green.

## How it works

1. **The declaration.** Every check declares one change to the **subject** (the code under test, its input, its fixture, or its environment) that must make the check fail. The change is ordinary code you write, applied through a patching handle that reverts everything afterwards. Nothing is generated, nothing is edited on disk, and no model is involved.
2. **Three runs at most.** The check runs as written and must pass. It runs again under the declared change, as a whole fresh test (setup, call and teardown), and must fail with an assertion. If it did, it runs a third time without the change, and must pass again. That control run is what stops a check that fails on its own second execution from being credited to the change.
3. **Four verdicts.**

| Verdict | Meaning |
|---|---|
| **proven** | Passed as written, failed under its declared change, and passed again without it. |
| **failed** | Failed as written. An ordinary red check. |
| **false** | Passed as written, and still passed under its declared change. The check is wrong. **This fails the build.** |
| **unproven** | Nothing is known yet: no declaration, or the failure under the change could not be attributed to it. Fails the build in strict mode. |

The verdict line carries its denominator, so a suite where nothing was graded can never read as a suite where everything was:

```
falsetto: 12 proven, 1 failed, 2 false, 3 unproven (18 graded of 21 run; 2 skipped, 1 excluded)
```

A false check is a real pytest failure: stop-on-first-failure stops on it, `--lf` reruns it, JUnit output counts it, and the exit status reflects it.

## Why now

Agents now write and run tests at scale. A false-green test is the failure that scales silently: it hides a defect behind a passing suite, and nothing in today's runners can see it. Falsetto bites twice.

- **At authoring.** The agent, or the person, must answer "what change should make this red" before the test exists. Tests written to answer that question are better on the first run. Strict mode makes the answer mandatory.
- **On vacuity.** A change elsewhere makes a proven test unable to fail, and it slides from proven to false without anyone touching it. Falsetto catches it on the change that did it.

## Evals too

An evaluation cell is a check. Its declared change is a planted wrong answer or a null baseline: swap the model for random output, or hand the judge a known-bad response, and the score must collapse. A judge that scores garbage high is a **false** eval. An eval minted at runtime without its falsifier is **unproven**, never a pass. Falsetto is meant for unit tests, integration tests, and evals, whether the evals are static or constructed on the fly.

## Using it

```
pip install -e .            # from a clone; not yet on PyPI
pytest --falsetto           # grade every function-based check
pytest --falsetto-strict    # and count unproven checks as failures
pytest --falsetto --falsetto-json=verdicts.json
```

Or in `pyproject.toml`, so the flag is never forgotten:

```toml
[tool.pytest.ini_options]
falsetto = true
falsetto_strict = true
```

Falsetto is inert unless enabled. A check that cannot be proven on purpose, such as one that talks to a live service, is excluded with `@pytest.mark.no_proof("reason")`; it is counted as excluded in the verdict line and is never a pass.

**The declaration.** `@falsetto.must_fail_when(change, *, expect=None, describe=None)`. `change` receives a handle with `setattr`, `setitem`, `delattr`, `delitem`, `setenv` and `delenv`; everything it does is undone after the run. By default the check must fail with an `AssertionError` or a `pytest.fail`; any other exception is "wrong reason", never proof. Pass `expect=SomeError` when the failure you mean is a different one. Pass `describe="..."` to name the change in reports.

**Beyond pytest.** `falsetto.check_callable(fn, declaration)` grades a plain callable with the same verdicts, for a bespoke harness. The pytest plugin is one adapter over that core; nothing else computes a verdict.

## What Falsetto needs from your tests

- **Repeatability.** A graded check runs up to three times. A check whose second run fails on its own, because it counts calls at module level or consumes something shared, is reported unproven with a hint, never proven.
- **Changes through the handle.** A declaration that mutates state without the handle is not reverted, and its damage lands on a later test.
- **Names looked up at call time.** Patching `module.function` does not reach a name the test copied in with `from module import function`. The hint on a false verdict says so.

Falsetto grades function-based checks, including `unittest.TestCase` methods. Doctests and custom item types are left to pytest and counted as not gradable.

## Status

Pre-alpha, installable from source. The design is in [docs/design.md](docs/design.md), the build plan in [docs/plan.md](docs/plan.md), and what came before in [docs/prior-art.md](docs/prior-art.md). The router example under `examples/router` prints one check per verdict:

```
pytest examples/router --falsetto
```

## Licence

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
