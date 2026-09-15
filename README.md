# Falsetto

A test runner that refuses to count a check unless it can prove the check is capable of failing.

Test runners report two states: pass and fail. They hide a third: a test that cannot fail. It stays green because the thing it checks is missing on both sides, or the fixture is empty, or the assertion compares nothing to nothing. Such a test proves nothing, and it looks exactly like a test that proves everything.

Falsetto makes that third state visible, and it screams when it finds one.

## The problem, in one example

A message router copies a thread key from the incoming message onto the outgoing route.

```python
def test_route_keeps_thread_key(msg):
    route = pick_route(msg)
    assert route.thread_key == msg.thread_key
```

Falsetto asks the author one question: what change should make this red? The author declares it: `pick_route` drops the thread key. Falsetto runs the test under that change, the assertion trips, and the test is **proven**.

A month later a colleague simplifies the shared fixture in another file, so `msg.thread_key` now defaults to `None`. Every test still passes. This one now asserts `None == None`. Under the declared change it still passes, because a dropped key is also `None`. Falsetto reports it **false** on that pull request. Nobody touched the test. Every other runner said green.

## What Falsetto does

1. Every check declares one change to the **subject** (the code under test, its input, its fixture, or its environment) that must make the check fail, and the failure it expects. The declaration is never a change to the test itself.
2. Falsetto runs the check twice: once as written, where it must pass, and once under the declared change, applied in-process and reverted automatically, where it must fail for the stated reason.
3. Each check gets one of four verdicts.

| Verdict | Meaning |
|---|---|
| **proven** | Passed as written, and failed under its declared change. |
| **failed** | Failed as written. An ordinary red test. |
| **false** | Passed as written, and still passed under its declared change. The test is wrong. |
| **unproven** | No declaration, or it failed under the change for a reason other than the one declared. Nothing is known yet. |

The verdict line reads:

```
falsetto: 12 proven, 1 failed, 2 false, 3 unproven
```

A green that cannot go red is never counted as a pass.

## Why now

Agents now write and run tests at scale. A false-green test is the failure that scales silently: it hides a defect behind a passing suite, and nothing in today's runners can see it. Falsetto bites twice.

- **At authoring.** The agent, or the person, must answer "what change should make this red" before the test exists. Tests written to answer that question are better on the first run.
- **On vacuity.** A change elsewhere makes a proven test unable to fail, and it slides from proven to false without anyone touching it. Falsetto catches it on the change that did it.

## Evals too

An evaluation cell is a check. Its declared change is a planted wrong answer or a null baseline: swap the model for random output, or hand the judge a known-bad response, and the score must collapse. A judge that scores garbage high is a **false** eval. An eval minted at runtime without its falsifier is **unproven**, never a pass. Falsetto is meant for unit tests, integration tests, and evals, whether the evals are static or constructed on the fly.

## Status

Pre-alpha, installable from source, not yet on PyPI.

```
pip install -e .
pytest examples/router          # the four verdicts, one check each
pytest                          # Falsetto's own checks, each one proven
```

The design is in [docs/design.md](docs/design.md) and the build plan in [docs/plan.md](docs/plan.md).
