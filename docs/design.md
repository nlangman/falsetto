# Falsetto design

Status: design record, pre-alpha. Written before any code, so that the skeleton compiles against a settled shape. Sections marked *open* are settled by the skeleton, not by more prose.

## 1. Thesis

A check counts only once it is provably falsifiable. The unit of proof is a declared change to the subject under which the check must fail for a stated reason. Everything else in Falsetto follows from that sentence.

## 2. Vocabulary

- **Check**: a unit test, an integration test, or an evaluation cell.
- **Subject**: what the check is about: code under test, its input, its fixture, or its environment. Never the check itself.
- **Declaration**: the change to the subject that must make the check fail, plus the failure it expects.
- **Positive run**: the check as written. Must pass.
- **Negative run**: the check under the declaration. Must fail for the stated reason.
- **Verdict**: proven, failed, false, unproven.

## 3. The declaration

A declaration names two things.

1. **The change.** A callable that mutates the subject in-process for the duration of the negative run: patch a function, replace an attribute, alter an input, swap a fixture, set an environment variable. It is applied through a scoped patching handle so the revert is automatic. Falsetto never edits files on disk.
2. **The expected failure.** By default, an `AssertionError` raised from the check's own frame. Optionally narrower: a named assertion, an exception type, or a predicate over the failure. The default is deliberately strict enough to reject "it crashed somewhere" as proof.

The change is to the subject, never to the check. Mutating the check's own assertion proves only that the assertion is sensitive to itself.

The shape as built. The decorator attaches the declaration to the function and returns it unchanged, so fixture resolution is untouched:

```python
import falsetto


@falsetto.must_fail_when(
    lambda m: m.setattr(router, "pick_route", pick_route_dropping_thread_key),
)
def test_route_keeps_thread_key(msg):
    route = router.pick_route(msg)
    assert route.thread_key == msg.thread_key
```

`must_fail_when(change, *, expect=AssertionError, describe=None)`. The handle is pytest's `MonkeyPatch`, so `setattr`, `setitem`, `delattr`, `setenv` and `delenv` all revert automatically. Input and fixture mutations ride the same handle for now; a dedicated form is *open* until a real suite asks for one.

## 3a. One core, many front-ends

Only `falsetto.core` computes verdicts. `core.prove(run, declaration, subject)` performs the negative run given a plain callable that executes the check once; `core.check(...)` performs both runs for a front-end that does not run checks itself. The pytest plugin is an adapter: pytest performs the positive run, and the plugin hands `item.runtest` to `core.prove`. A bespoke harness, or a port, calls the same functions. There is no second implementation of the four states anywhere, which is what keeps every front-end from drifting.

## 4. The two runs and the four verdicts

| Positive run | Negative run | Declared? | Verdict |
|---|---|---|---|
| pass | fails for the stated reason | yes | **proven** |
| pass | passes | yes | **false** |
| pass | fails for another reason | yes | **unproven** (wrong reason) |
| pass | not run | no | **unproven** (undeclared) |
| fail | not run | any | **failed** |

Two verdicts are non-green for different reasons and are counted separately. **False** is a defect in the check. **Unproven** is missing evidence. Conflating them would let a suite hide its wrong tests among its undeclared ones.

The verdict line: `falsetto: N proven, N failed, N false, N unproven`. Exit status is non-zero on any failed or false. Whether unproven is a warning or a failure is a configuration switch. Strict is the recommended setting for suites written by agents.

## 5. Vacuity

Vacuity is the regression only Falsetto can see. A change elsewhere makes a proven check unable to fail, and it slides from proven to false without anyone touching it. The README example is the canonical case: a fixture simplification in another file turns an assertion into `None == None`, and the declared change no longer bites. Ordinary regressions are caught by the positive run, as in any runner. Vacuity is caught by the negative run, on the change that introduced it.

## 6. Evals

An evaluation cell is a check whose subject is a model, a judge, or a pipeline of both. Its declaration is a falsifier:

- **Null baseline**: replace the model with random or constant output. The metric must collapse below the acceptance threshold.
- **Planted wrong answer**: hand the judge a response known to be wrong. The judge must score it low.
- **Withheld input**: remove the information the answer depends on. The score must drop.

A judge that scores garbage high is a **false** eval. An eval constructed at runtime, by an agent or a pipeline, that arrives without its falsifier is **unproven**, never a pass.

Two design notes. Statistical evals need a change strong enough to move the aggregate, so a single planted sample is a weak falsifier for a metric over hundreds of samples, and the null baseline is the reliable one. And a use-case definition format that already carries acceptance criteria and a judge can carry its falsifier as a field, which is how Falsetto attaches to an evaluation framework without owning it.

## 7. Feedback for agents

The report has two forms: a human line per non-green verdict, shipped, and a JSON record per check, planned.

```json
{"check": "tests/test_router.py::test_route_keeps_thread_key",
 "verdict": "false",
 "declared": "setattr(router, 'pick_route', pick_route_dropping_thread_key)",
 "reason": "negative run passed",
 "hint": "The assertion does not observe the declared change, or the fixture is the tautology. Check what both sides of the assertion evaluate to under the change."}
```

Hints are written for the author who has to act, and an agent is the expected author. The two standard hints:

- **unproven, undeclared**: "Declare the change to the subject that should make this check fail."
- **false**: "Under the declared change this check still passed. Either the assertion does not observe the change, or the fixture is the tautology."

The core is runner-agnostic and emits the JSON. A thin integration layer can surface hints inside an agent's coding session while it authors tests. That layer is optional and separate.

## 8. Proof cache

Every check runs twice, which doubles the cost of the negative runs for integration and live cells. Proofs are cached on a key of the check's source, the declaration's source, and the subject files the declaration touches. A cached proof is reused until any of those change. A `--prove-all` switch forces every negative run. The cache is a local file and never substitutes for the run on the change that introduced a regression.

## 9. Relation to mutation testing

Whole-program mutation tools generate many mutants across a codebase and report a kill ratio: what fraction of mutants some test caught. Falsetto asks each check for one intended mutant and reports a verdict per check. Three consequences:

- **Fast.** Two runs per check, cacheable, instead of a run of the suite per mutant.
- **Intentional.** The author's claim about what the check detects is itself checked, which is where the authoring feedback comes from.
- **A third state.** A kill ratio cannot say "this specific check is false." A per-check verdict can.

The two are complementary. Falsetto does not generate mutants and does not aim to. The nearest neighbours, pytest-mutagen (hand-declared mutants, 2020) and spec-verify (one targeted mutation per acceptance criterion inside an agent workflow, 2026), and the pseudo-tested-methods literature are described in [prior-art.md](prior-art.md), with what each lacks that Falsetto adds.

## 10. Non-goals

- Generating mutants.
- Replacing the test runner. Falsetto is a plugin over an existing runner.
- Coverage measurement.
- A hosted service.

## 11. Hypothesis for the first increments

Pointed at suites we currently believe are green, Falsetto sorts them into proven, false and unproven, and finds at least one false or unproven check that a human confirms is real.

- **Validates**: at least one confirmed false or unproven check in our own suites, including the suite that once reported fully green with a real defect inside.
- **Invalidates**: every check is trivially proven, or the in-process patching model does not fit real checks without editing files. Either result is a new decision, not a reason to keep building.

## 12. Targets

Python with a pytest plugin first. A Swift Testing port second. The verdict model is language-neutral, and both targets share the vocabulary above.
