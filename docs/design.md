# Falsetto design

Status: design record, pre-alpha, kept in step with the code. The first version was written before any code; the second recorded the run seam after review round one; the third the boundary and the control-first order after review round two; this one the reach of the scope guard, the control count and run isolation after review round three.

## 1. Thesis

A check counts only once it is provably falsifiable. The unit of proof is a declared change to the subject under which the check must fail for a stated reason, after a run without the change that passes. Everything else in Falsetto follows from that sentence.

## 2. Vocabulary

- **Check**: a unit test, an integration test, or an evaluation cell.
- **Subject**: what the check is about: code under test, its input, its fixture, or its environment. Never the check itself.
- **Declaration**: the change to the subject that must make the check fail, the failure it expects, and how deep the change reaches (its scope).
- **Positive run**: the check as written. Must pass.
- **Control run**: the check again, unchanged, from a fresh boundary. Must pass. It runs before the negative run, so any check that does not pass on its second execution is caught before a failure could be credited to the change. `k` control runs catch residue that first appears up to execution `k + 1`; the default is one, and the control runs are unconditional, so a false check also costs three runs. That order is deliberate: running the negative run first would put its residue ahead of the control.
- **Negative run**: the check under the declaration, from the same fresh boundary. Must fail for the stated reason.
- **Boundary**: the fixture scopes that are rebuilt for every run of a check, named by the declaration's scope. Wider scopes stay alive across the runs.
- **Verdict**: proven, failed, false, unproven.

## 3. The declaration

`must_fail_when(change, *, expect=None, describe=None, scope="function")` attaches a `Declaration` to the check and returns the function unchanged, so the runner's fixture resolution is untouched. Applying it twice is an error; an unknown scope is an error.

**The change** is a callable receiving a `Patch`, Falsetto's own scoped handle: `setattr`, `setitem`, `delattr`, `delitem`, `setenv`, `delenv`, each recorded and undone in reverse order when the handle's block ends. An undo step that raises does not stop the others. An attribute the target inherited is restored as inherited. The change is ordinary code the author writes and is applied by calling it; nothing is generated and no file is edited. The change is to the subject, never to the check.

**The expected failure.** `expect` is None by default, which means the front-end's default applies: for the pytest plugin, `AssertionError` or pytest's own `Failed`; for the core, `AssertionError`. Any other exception is "wrong reason", so "it crashed somewhere" is never proof. An exception type, a tuple of types, or a predicate narrows or widens it, and a non-default expectation is shown next to the declaration in every report.

**The scope** says which fixture scopes are rebuilt under the change: function (the default), class, module, package or session. It is the teardown boundary for every run of the check, so a verdict never depends on what pytest happens to run next, in serial or under xdist. A class scope on a check that is not in a class is misconfigured. A session scope rebuilds the session's fixtures for that check and for every test after it.

**The reach of the scope guard.** When the negative run passes, Falsetto asks whether the change had every chance to bite. It reads every fixture pytest resolved for the check, by any route: named in the signature, reached through another fixture, autouse, `usefixtures`, or requested dynamically. Fixtures defined by pytest itself or by an installed plugin are infrastructure and never count; fixtures the suite defines do. If any counted fixture is wider than the declaration's scope, the verdict is unproven and out of scope, with the fixture and the scope named, and it fails the build: the check cannot be graded under its declaration. It is never called false, because the change may never have reached that fixture, and it is never a pass, because a genuinely false check must not escape behind a wide fixture.

## 3a. One core, many front-ends

`falsetto.core` is the only place a verdict is computed, and it imports nothing from pytest. A front-end supplies one thing: how to run the check once, as a callable returning a `RunResult` (passed, failed with the exception, location, summary and text, skipped, or errored). `core.prove(run, declaration, positive, wider_fixtures=...)` drives the control and negative runs and classifies; `core.check(run, declaration)` performs the positive run too; `core.check_callable(fn, declaration)` grades a plain callable and always returns a verdict. The pytest plugin is an adapter over `prove`. There is no second implementation of the four states anywhere.

## 4. The runs and the verdicts

| Positive | Control | Negative | Verdict | Reason code |
|---|---|---|---|---|
| fails | not run | not run | **failed** | positive-failed |
| passes | no declaration | not run | **unproven** | undeclared |
| passes | does not pass | not run | **unproven** | not-repeatable |
| passes | passes | the change could not be applied | **unproven** | not-applied |
| passes | passes | passes, and the check uses a suite-defined fixture wider than the scope | **unproven** | out-of-scope (fails the build) |
| passes | passes | passes | **false** | negative-passed |
| passes | passes | skipped, or setup or teardown failed | **unproven** | wrong-reason |
| passes | passes | fails with an unexpected exception | **unproven** | wrong-reason |
| passes | passes | fails for the stated reason | **proven** | stated-reason |
| any | | | **unproven** | misconfigured (fails the build): a `no_proof` marker without a reason or beside a declaration, or a class scope outside a class |
| any | | | **unproven** | internal-error (Falsetto itself raised while grading) |

A positive run that was skipped or could not complete yields no verdict; the check is counted in the denominator as skipped or errored, never as a pass.

**False**, **internal-error**, **out-of-scope**, **misconfigured** and, in strict mode, every **unproven** fail the build. They do so by being real failures of the check's own report, so the runner's machinery for stopping, rerunning, reporting and exiting sees them without any side channel. An internal error is appended to the check's own failure text when there is one, never written over it, and it is reported on whatever report exists when there is no call report.

The verdict line always carries its denominator: `N proven, N failed as written, N false, N unproven (G graded of R run; ...)` with skipped, errored, excluded, xfail, not-gradable, incomplete, not-graded (another plugin ran the protocol) and teardown-failed-after-grading counts when non-zero. In strict mode, a session that ran anything and graded nothing fails, whatever the reason; modes that run nothing are exempt.

## 5. Vacuity

Vacuity is the regression only Falsetto can see. A change elsewhere makes a proven check unable to fail, and it slides from proven to false without anyone touching it. The README example is the canonical case: a fixture simplification in another file turns an assertion into `None == None`, and the declared change no longer bites. Ordinary regressions are caught by the positive run, as in any runner. Vacuity is caught by the negative run, on the change that introduced it.

Known limits, stated plainly. Proof is granted per check, and one assertion sensitive to the declared change certifies the whole check. One control run catches any check that does not pass on its second execution; residue that first appears on the third execution is credited to the change and reported proven, and a second control run (`--falsetto-controls 2`) catches it. Residue that masks a change, such as a cache warmed by an earlier run, produces a false verdict for a correct check, and the hint names it. Fixtures wider than the declaration's scope are never rebuilt under the change; the out-of-scope verdict says so rather than accusing the check, and fails the build rather than letting a false check through.

## 6. The pytest adapter

The plugin is inert unless enabled with `--falsetto`, `--falsetto-strict`, or the `falsetto` and `falsetto_strict` ini keys. When enabled it takes over the run protocol for function-based items, including `unittest.TestCase` methods. Every run of a declared check is a whole unlogged protocol (setup, call, teardown) torn down to the declaration's boundary; after the runs, the fixture stack is torn down to what the real next item needs, and a failure there becomes a teardown report. Each run is observed through its reports, which is what makes `unittest` items grade correctly. The exception behind a failed call is captured from the report hook for the expectation check. The positive run's reports are logged once, with the verdict attached as one JSON record on the call and teardown reports' `user_properties`, appended last, so it survives serialization under xdist and appears in JUnit output as a parseable property. A test that records a property under the same name cannot change Falsetto's verdict or its enforcement, though its own record still appears in JUnit beside Falsetto's.

The control and negative runs execute with coverage measurement paused, so a hand-written stub cannot inflate a coverage gate, and with the `--pdb` and `--trace` plugins unregistered, so a deliberate failure never opens a debugger; other consumers of `pytest_exception_interact` still see those failures. A timeout plugin that arms one budget per protocol spends it across all runs. `--durations` reports the positive run only. After the graded runs the fixture stack is torn down to what the real next item needs, or entirely when the session is about to stop, by the same call pytest's teardown hook makes; that final teardown does not re-enter per-phase plugin hooks, and a failure in it is merged into the check's teardown report, so it is one error on one JUnit testcase and is counted in the verdict line. Captured output of the control and negative runs is not logged; the failure text of a run that decided a verdict travels as evidence in the verdict record and is printed in the summary. Doctests and custom item types are left to pytest and counted as not gradable. `@pytest.mark.no_proof(reason)` excludes a check; the reason is required, the check is listed by name, and it is counted as excluded, never as a pass. `--falsetto-json PATH` writes every verdict, with reason codes, messages, hints, details and evidence, plus the totals, the not-graded items, and whether the session ran to completion or stopped early and why; the directory is created if needed, and a report that cannot be written is an internal-error exit, never a green build with a missing channel.

Plugins that also take over the run protocol, such as rerun plugins, compete with Falsetto for each check, and whichever pytest calls first wins. Falsetto names them in a warning at startup, and a gradable check it did not get to grade is reported as not graded, never as a pass.

## 7. Feedback for agents

Every verdict carries a stable reason code, a sentence, and for non-green verdicts a hint written for the author who has to act, and an agent is the expected author. The terminal summary lists false and unproven checks with their declared change, detail, hint and the evidence lines of the run that decided it. The JSON report is the machine channel. The standard hints:

- **undeclared**: declare the change to the subject that should make this check fail.
- **false**: the assertion does not observe the change, the fixture is the tautology, the change never reached the subject, or earlier residue masked it.
- **wrong-reason**: narrow the change, or pass `expect=` if the failure you see is the one you mean.
- **not-repeatable**: build the check's state in fixtures, not at module level.
- **out-of-scope**: widen `scope=` so the fixtures the check uses are rebuilt under the change.
- **not-applied**: fix the declared change; nothing is known about the check until it applies.
- **misconfigured**: give `no_proof` a reason, do not combine it with a declaration, and use a scope the check can have.
- **internal-error**: a bug in Falsetto or in a hook it called; report it.

## 8. Proof cache

Every declared check runs three times, which is the cost of attribution. Proofs will be cached, and the key must be coarse on purpose: the check's source, every conftest on its path, and every file of the subject's package. A finer key that missed a fixture change in another file would cache away the vacuity catch, which is the one regression the project exists for. The cache never substitutes for the run on the change that introduced a regression. Not built yet.

## 9. Relation to mutation testing

Whole-program mutation tools generate many mutants across a codebase and report a kill ratio. Falsetto asks each check for one intended mutant, written by hand, and reports a verdict per check, with a control run. Three consequences: fast (three runs per check, cacheable), intentional (the author's claim about what the check detects is itself checked, which is where the authoring feedback comes from), and a third state a kill ratio cannot express: this specific check is false. The two are complementary. Falsetto does not generate mutants and does not aim to. The nearest neighbours, pytest-mutagen (hand-declared mutants, 2020) and spec-verify (one targeted mutation per acceptance criterion inside an agent workflow, 2026), and the pseudo-tested-methods literature are described in [prior-art.md](prior-art.md).

## 10. Non-goals

- Generating mutants.
- Replacing the test runner. Falsetto is a plugin over an existing runner.
- Coverage measurement.
- A hosted service.

## 11. Hypothesis for the first increments

Pointed at suites we currently believe are green, Falsetto sorts them into proven, false and unproven, and finds at least one false or unproven check that a human confirms is real.

- **Validates**: at least one confirmed false or unproven check in our own suites, including the suite that once reported fully green with a real defect inside.
- **Invalidates**: every check is trivially proven, or the in-process patching model does not fit real checks without editing files. Either result is a new decision, not a reason to keep building.

Already observed while building: across two rounds Falsetto reported six of its own author's checks false and four unproven, each for a real reason.

## 12. Targets

Python with a pytest plugin first. A Swift Testing port second. The core's vocabulary (run result, declaration with scope, patch handle, the four verdicts with reason codes) is language-neutral, and a port implements exactly that.
