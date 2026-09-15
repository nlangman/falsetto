# Falsetto plan

Increments in order. Each names the check that proves it and leaves the tree green. Status is updated in place.

| # | Increment | Proving check | Status |
|---|---|---|---|
| 0 | Founding: design record, this plan, a leak gate on commits and commit messages, proven red | The gate blocks a commit carrying a planted term and admits the founding docs | done |
| 1 | Skeleton: declaration API, runner-agnostic core (`falsetto.core`), pytest adapter, verdict line, the router example, package metadata | `pytest examples/router` prints `1 proven, 1 failed, 1 false, 1 unproven`; Falsetto's own suite is all proven | done |
| 2 | Vacuity demo: the README example as a script that applies the fixture change and re-runs | The verdict line changes between the two fixture states | next |
| 3 | Dogfood on our own suites | At least one confirmed false or unproven check found | |
| 4 | Eval falsifier with a fake judge | A judge that scores garbage high reports the eval false | |
| 5 | Proof cache keyed on check plus subject | A second run skips negative runs; touching the subject re-runs them | |
| 6 | Agent feedback: a JSON report per check (the human hint lines shipped in 1) | Each record names the check, the verdict and the reason | |
| 7 | Public release: README for strangers, licence, package name, history sweep, visibility flip | The leak gate over the full history is clean, and proven red on a planted term first | |

## Example project

A small router application in `examples/router/` with five checks, one per verdict plus the eval case: proven, failed, false, unproven, and a false eval with a fake judge. A script applies the README's fixture change and re-runs, so a reader watches proven become false.

## Out of scope

- Generating mutants across a codebase.
- Runner-specific features beyond the pytest plugin surface.
- The agent-session integration layer, beyond emitting the JSON that layer would read.

## Decisions pending

- Licence. Chosen before increment 7.
- Declaration form for input and fixture mutations beyond the patching handle. Not needed so far; revisit at increment 3.
- Default for unproven: warning or failure. Strict recommended.
- Timing of the Swift Testing port.

## Release protocol

The visibility flip is the only irreversible act. Before it:

1. The leak gate runs over the full history, not just the tree, and is proven red on a planted term first.
2. A licence file and the package name are in place.
3. The maintainer reads every file in the repository.
4. Prior-art characterizations in the design are verified.
