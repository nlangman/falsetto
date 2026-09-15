# Falsetto design

Status: design record, pre-alpha, kept in step with the code. The first version was written before any code; this one records the shape after the first review round, which changed the run seam.

## 1. Thesis

A check counts only once it is provably falsifiable. The unit of proof is a declared change to the subject under which the check must fail for a stated reason, confirmed by a run without the change that passes. Everything else in Falsetto follows from that sentence.

## 2. Vocabulary

- **Check**: a unit test, an integration test, or an evaluation cell.
- **Subject**: what the check is about: code under test, its input, its fixture, or its environment. Never the check itself.
- **Declaration**: the change to the subject that must make the check fail, plus the failure it expects.
- **Positive run**: the check as written. Must pass.
- **Negative run**: the check under the declaration. Must fail for the stated reason.
- **Control run**: the check again, without the declaration. Must pass. It attributes the negative run's failure to the change rather than to the check's own residue.
- **Verdict**: proven, failed, false, unproven.

## 3. The declaration

`must_fail_when(change, *, expect=None, describe=None)` attaches a `Declaration` to the check and returns the function unchanged, so the runner's fixture resolution is untouched. Applying it twice is an error.

**The change** is a callable receiving a `Patch`, Falsetto's own scoped handle: `setattr`, `setitem`, `delattr`, `delitem`, `setenv`, `delenv`, each recorded and undone in reverse order when the handle's block ends. The change is ordinary code the author writes and is applied by calling it; nothing is generated and no file is edited. The change is to the subject, never to the check: mutating the check's own assertion proves only that the assertion is sensitive to itself.

**The expected failure.** `expect` is None by default, which means the front-end's default applies: for the pytest plugin, `AssertionError` or pytest's own `Failed` (from `pytest.fail` and a missed `pytest.raises`); for the core, `AssertionError`. Any other exception is "wrong reason", so "it crashed somewhere" is never proof. An exception type, a tuple of types, or a predicate narrows or widens it, and a non-default expectation is shown next to the declaration in every report, so a permissive predicate is visible to a reviewer. The first version also required the assertion to be raised in the check's own frame; that rejected shared assertion helpers and every `unittest` assert method, and it was dropped.

## 3a. One core, many front-ends

`falsetto.core` is the only place a verdict is computed, and it imports nothing from pytest. A front-end supplies one thing: how to run the check once, as a callable returning a `RunResult` (passed, failed with the exception and its location, skipped, or errored). `core.prove(run, declaration, positive)` drives the negative and control runs and classifies; `core.check(run, declaration)` performs the positive run too; `core.check_callable(fn, declaration)` grades a plain callable. The pytest plugin is an adapter over `prove`. A bespoke harness, or a port, calls the same functions. There is no second implementation of the four states anywhere, which is what keeps front-ends from drifting.

## 4. The runs and the verdicts

| Positive | Negative | Control | Verdict | Reason code |
|---|---|---|---|---|
| fails | not run | not run | **failed** | positive-failed |
| passes | no declaration | not run | **unproven** | undeclared |
| passes | the change could not be applied | not run | **unproven** | not-applied |
| passes | passes | not run | **false** | negative-passed |
| passes | skipped, or setup or teardown failed | not run | **unproven** | wrong-reason |
| passes | fails with an unexpected exception | not run | **unproven** | wrong-reason |
| passes | fails for the stated reason | passes | **proven** | stated-reason |
| passes | fails for the stated reason | fails | **unproven** | not-repeatable |
| any | Falsetto itself raised while grading | | **unproven** | internal-error |

A positive run that was skipped or could not complete yields no verdict; the check is counted in the denominator as skipped or errored, never as a pass.

**False** and **internal-error** fail the build. **Unproven** fails the build in strict mode. They do so by being real failures of the check's own report, so the runner's machinery for stopping, rerunning, reporting and exiting sees them without any side channel. An internal error is reported as Falsetto's failure, with its traceback, never disguised as the check failing as written.

The verdict line always carries its denominator: `N proven, N failed, N false, N unproven (G graded of R run; ...)` with skipped, errored, excluded, xfail and not-gradable counts when non-zero. In strict mode, a session that ran gradable checks and graded none fails: an emptied suite reports nothing, never a pass.

## 5. Vacuity

Vacuity is the regression only Falsetto can see. A change elsewhere makes a proven check unable to fail, and it slides from proven to false without anyone touching it. The README example is the canonical case: a fixture simplification in another file turns an assertion into `None == None`, and the declared change no longer bites. Ordinary regressions are caught by the positive run, as in any runner. Vacuity is caught by the negative run, on the change that introduced it.

Known limits, stated plainly. Proof is granted per check, and one assertion sensitive to the declared change certifies the whole check, including other assertions that may be tautological. Residue from the positive run can mask a change (a cache warmed by the first run) and produce a false verdict for a correct check; the hint names it. Checks must be repeatable, since a graded check runs up to three times; the control run turns a non-repeatable check into unproven rather than a manufactured proof.

## 6. The pytest adapter

The plugin is inert unless enabled with `--falsetto`, `--falsetto-strict`, or the `falsetto` and `falsetto_strict` ini keys. When enabled it takes over the run protocol for function-based items, including `unittest.TestCase` methods: it runs the positive run as a whole unlogged protocol (setup, call, teardown), then, if the call passed and is not an xfail, the negative and control protocols the same way with the declared change applied before setup, so fixture-level and input-level changes bite. Each run is observed through its reports, which is what makes `unittest` items, whose failures are recorded rather than raised, grade correctly. The exception behind a failed call is captured from the report hook for the expectation check. The positive run's reports are then logged once, with the verdict attached as a JSON string on the call and teardown reports' `user_properties`, so it survives serialization under xdist and appears in JUnit output as one parseable property.

Doctests and custom item types are left to pytest and counted as not gradable. `@pytest.mark.no_proof(reason)` excludes a check from grading; it is counted as excluded, never as a pass. `--falsetto-json PATH` writes every verdict, with reason codes, messages, hints and details, plus the totals and the not-graded items.

Other plugins that replace the run protocol, such as rerun plugins, are not yet compatible; Falsetto's protocol runs first and returns.

## 7. Feedback for agents

Every verdict carries a stable reason code, a sentence, and for non-green verdicts a hint written for the author who has to act, and an agent is the expected author. The terminal summary lists false and unproven checks with their declared change, detail and hint. The JSON report is the machine channel. The standard hints:

- **undeclared**: declare the change to the subject that should make this check fail.
- **false**: the assertion does not observe the change, the fixture is the tautology, or the change never reached the subject.
- **wrong-reason**: narrow the change, or pass `expect=` if the failure you see is the one you mean.
- **not-repeatable**: build the check's state in fixtures, not at module level.

## 8. Proof cache

Every proven check runs three times, which is the cost of attribution. Proofs will be cached, and the key must be coarse on purpose: the check's source, every conftest on its path, and every file of the subject's package. A finer key that missed a fixture change in another file would cache away the vacuity catch, which is the one regression the project exists for. The cache never substitutes for the run on the change that introduced a regression. Not built yet.

## 9. Relation to mutation testing

Whole-program mutation tools generate many mutants across a codebase and report a kill ratio. Falsetto asks each check for one intended mutant, written by hand, and reports a verdict per check, with a control run. Three consequences: fast (at most three runs per check, cacheable), intentional (the author's claim about what the check detects is itself checked, which is where the authoring feedback comes from), and a third state a kill ratio cannot express: this specific check is false. The two are complementary. Falsetto does not generate mutants and does not aim to. The nearest neighbours, pytest-mutagen (hand-declared mutants, 2020) and spec-verify (one targeted mutation per acceptance criterion inside an agent workflow, 2026), and the pseudo-tested-methods literature are described in [prior-art.md](prior-art.md).

## 10. Non-goals

- Generating mutants.
- Replacing the test runner. Falsetto is a plugin over an existing runner.
- Coverage measurement.
- A hosted service.

## 11. Hypothesis for the first increments

Pointed at suites we currently believe are green, Falsetto sorts them into proven, false and unproven, and finds at least one false or unproven check that a human confirms is real.

- **Validates**: at least one confirmed false or unproven check in our own suites, including the suite that once reported fully green with a real defect inside.
- **Invalidates**: every check is trivially proven, or the in-process patching model does not fit real checks without editing files. Either result is a new decision, not a reason to keep building.

Already observed while building: Falsetto reported three of its own author's checks false and two unproven, each for a real reason.

## 12. Targets

Python with a pytest plugin first. A Swift Testing port second. The core's vocabulary (run result, declaration, patch handle, the four verdicts with reason codes) is language-neutral, and a port implements exactly that.
