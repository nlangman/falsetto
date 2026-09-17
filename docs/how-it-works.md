# How it works: one check, start to finish

This page traces a single declared check through the code, in execution order. The
design record says what and why; this says where. The rule to verify as you read:
only `falsetto.core` computes a verdict.

## The trace

1. **pytest hands the item over.** `plugin.pytest_runtest_protocol` runs first among the
   protocol implementations and, for a function-based item when Falsetto is enabled,
   takes the whole protocol. Modes that run nothing (`--collect-only`, `--setup-only`,
   `--setup-plan`) are left to pytest.
2. **The declaration is read.** `declaration.get_declaration` returns the `Declaration`
   the decorator attached to the function: the change, the expectation, the description,
   and the scope.
3. **The boundary is chosen.** `plugin._boundary` turns the declaration's scope into the
   node whose fixtures stay alive between runs. With the default scope that is the item's
   parent, so function-scoped fixtures are rebuilt for every run and wider ones are kept.
4. **The positive run.** `runtestprotocol(item, log=False, nextitem=boundary)` performs
   setup, call and teardown without logging. `plugin._observe` turns the three reports
   into a `RunResult`: passed, failed with the exception and its location, skipped, or
   errored. The exception behind a failed call is captured by the plugin's
   `pytest_runtest_makereport` wrapper.
5. **The core grades.** `core.prove(run, declaration, positive, ...)` receives a `run`
   callable that performs one more unlogged protocol at the same boundary, with coverage
   paused and the debugger plugins unregistered. The core runs the control runs, applies
   the change through a `Patch`, runs the negative run, reverts, and classifies. A revert
   that raises is `core._revert`'s own verdict, not-reverted: the subject is still patched,
   so nothing later in the session can be graded against it.
   `plugin._wider_fixtures` tells it which suite-defined fixtures the check used, by any
   route, beyond the declaration's scope, so a passing negative run becomes "out of scope"
   rather than "false" when the change may never have reached them.
6. **The real teardown.** For a declared check, `plugin._teardown_to` tears the fixture
   stack down to what the next item actually needs, or entirely when the session is about
   to stop, as pytest's own teardown would have; a failure there is merged into the check's
   teardown report, never silence.
7. **The verdict is attached.** `plugin._attach` puts the `Result` on the call and
   teardown reports as one JSON record under `falsetto.verdict`, appended last so nothing
   a test recorded under that name can win. A false verdict, a strict unproven verdict,
   an out-of-scope, misconfigured or not-reverted verdict, or an internal error marks the
   report failed and appends the reason to its text. On not-reverted, `plugin._attach` also
   sets `session.shouldfail`, so pytest stops after this item.
8. **The reports are logged once.** pytest's reporters, `-x`, `--lf`, JUnit and the exit
   status see the positive run's reports with the verdict already on them.
9. **The session tallies.** `plugin._Session.pytest_runtest_logreport` reads every logged
   report, on the controller under xdist too, and keeps the per-item status: graded,
   skipped, errored, excluded, xfail, not gradable, incomplete, not graded because another
   plugin ran the protocol, or teardown failed after grading. The summary section,
   the verdict line with its denominator, the strict rule, and `--falsetto-json` all read
   that tally.

```mermaid
sequenceDiagram
    participant pytest
    participant plugin as falsetto.plugin
    participant core as falsetto.core
    pytest->>plugin: pytest_runtest_protocol(item, nextitem)
    plugin->>pytest: runtestprotocol(item, log=False, nextitem=boundary)
    pytest-->>plugin: setup, call, teardown reports (positive)
    plugin->>core: prove(run, declaration, positive, wider_fixtures)
    core->>plugin: run()  (control, unchanged)
    plugin->>pytest: runtestprotocol(... boundary)
    pytest-->>plugin: reports -> RunResult
    core->>core: Patch: apply the declared change
    core->>plugin: run()  (negative, under the change)
    plugin->>pytest: runtestprotocol(... boundary)
    pytest-->>plugin: reports -> RunResult
    core->>core: revert; classify
    core-->>plugin: Result(verdict, reason, detail, evidence)
    plugin->>plugin: tear down to the real next item; attach the record; mark failures
    plugin->>pytest: pytest_runtest_logreport x3 (setup, call, teardown)
```

## What it looks like

The router example (`pytest examples/router`) has one check per verdict. Its Falsetto
section, verbatim; the proven check is silent, because a proof needs no action:

```text
=================================== falsetto ===================================
FALSE examples/router/test_router.py::test_route_queue_matches: still passed under the declared change
    declared: lambda m: m.setattr(router, "pick_route", pick_route_to_wrong_queue)
    hint: Either the assertion does not observe the change, the fixture is the tautology, the change never reached the subject (a name imported directly into the test module is not affected by patching its source module), or state warmed by an earlier run, such as a cache, masked the change.
UNPROVEN examples/router/test_router.py::test_ops_body_routes_to_ops: no declared change
    hint: Declare the change to the subject that should make this check fail.
falsetto: 1 proven, 1 failed as written, 1 false, 1 unproven (4 graded of 4 run)
=========================== short test summary info ============================
FAILED examples/router/test_router.py::test_route_queue_is_billing - Assertio...
FALSE examples/router/test_router.py::test_route_queue_matches - FALSE: still...
UNPROVEN examples/router/test_router.py::test_ops_body_routes_to_ops - UNPROV...
3 failed, 1 passed in 0.06s
```

The false and unproven checks are real failures in pytest's own summary, so `-x`, `--lf`,
JUnit and the exit status all see them. `--falsetto-json=verdicts.json` writes the same
verdicts, with reason codes and evidence, for a machine reader.

## Where a new front-end plugs in

A harness that is not pytest supplies one thing: a callable that runs its check once and
returns a `RunResult`. It then calls `core.check(run, declaration)` for the whole protocol,
or `core.check_callable(fn, declaration)` when the check is a plain callable. It receives
the same `Result`, with the same reason codes, and never computes a verdict of its own.
