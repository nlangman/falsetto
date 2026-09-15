# Falsetto plan

Increments in order. Each names the check that proves it and leaves the tree green. Status is updated in place.

| # | Increment | Proving check | Status |
|---|---|---|---|
| 0 | Founding: design record, this plan, a leak gate on commits and commit messages, proven red | The gate blocks a commit carrying a planted term and admits the founding docs | done |
| 1 | Skeleton: declaration, runner-agnostic core, pytest adapter, verdict line, the router example, package metadata | `pytest examples/router --falsetto` prints `1 proven, 1 failed as written, 1 false, 1 unproven` | done |
| 1b | The run seam, after review round one: whole-protocol runs with a control run, a pytest-free core with its own patch handle, opt-in by default, false checks as real failures, the denominator, loud internal errors, the JSON report, a test matrix over every class the reviewers broke | Falsetto's own suite is fully proven in strict mode; a check with a no-op declaration and its own residue is unproven, never proven | done |
| 1c | The boundary, after review round two: the declaration's scope is the teardown boundary for every run; the control run precedes the negative run; out-of-scope instead of false when a wider fixture was not rebuilt; coverage paused during graded runs; internal errors loud without a call report; a forge-proof verdict record; evidence in reports; a draining, inheritance-aware patch handle | Two byte-identical checks over a module fixture are proven whether first or last; an alternating check is unproven; the own suite is fully proven | done |
| 1d | The reach of the scope guard, after review round three: every fixture the check used by any route, infrastructure excluded; out-of-scope and misconfigured fail the build; a control-run count; descriptor-safe class patching; early-stop teardown; the post-grading teardown failure merged into the check's own report; debuggers paused; package scope; a completeness signal in the JSON report | Fixtures reached indirectly are out of scope, pytest's own session fixtures never shield a false check, and two control runs catch residue that appears on the third execution; the own suite is fully proven | done |
| 2 | Vacuity demo: the README example as a script that applies the fixture change and re-runs | The verdict line changes between the two fixture states | next |
| 3 | Dogfood on our own suites | At least one confirmed false or unproven check found | |
| 4 | Eval falsifier with a fake judge | A judge that scores garbage high reports the eval false | |
| 5 | Proof cache with a deliberately coarse key | A second run skips negative runs; a change to a fixture file in another directory re-runs them | |
| 6 | Agent-session integration over the JSON report | An unproven or false hint surfaces inside an agent's authoring session | |
| 7 | Public release: README for strangers, package name, history sweep, visibility flip | The leak gate over the full history is clean, and proven red on a planted term first | |

## Example project

A small router application in `examples/router/` with four checks, one per verdict. Increment 2 adds the script that applies the README's fixture change and re-runs, so a reader watches proven become false, and a fifth check with a fake judge arrives with increment 4.

## Out of scope

- Generating mutants across a codebase.
- Runner-specific features beyond the pytest plugin surface.
- Compatibility with plugins that replace the run protocol, until a design for sharing the protocol exists.

## Decisions pending

- Default for unproven: warning or failure. Strict recommended, and it is the repository's own setting.
- A string form for `setattr` targets (`"pkg.mod.name"`), if real suites ask for it.
- A guard against `scope="session"` in suites whose later tests rely on accumulated session state.
- Redaction of string literals in an auto-generated declaration description.
- `falsetto.excluded` can still be recorded by a test; it cannot turn a failure into a pass.
- A dedicated contact address for the code of conduct before the flip. That address is the maintainer's to provide.
- Timing of the Swift Testing port.

## Release protocol

The visibility flip is the only irreversible act. Before it:

1. The leak gate runs over the full history, not just the tree, and is proven red on a planted term first.
2. The package name is in place. The licence already is.
3. The maintainer reads every file in the repository.
4. Every entry in `docs/prior-art.md` is re-read against its primary source.
5. A release workflow with trusted publishing, a tag protocol, and a wheel install smoke test exist in CI.
