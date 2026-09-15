# Contributing to Falsetto

Thank you for considering a contribution. This page is short because the rules are few.

## Set up

```
git clone https://github.com/nlangman/falsetto
cd falsetto
uv sync                 # creates .venv with the package and the dev tools
uv run pytest           # Falsetto's own checks, in strict mode
uv run pytest examples/router   # the repository's strict setting applies, so exit 1 is expected
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

Any Python 3.10 or newer works. `uv` is the fastest path, but a plain virtual
environment with `pip install -e . ruff mypy` is fine.

## The one rule

**Every check declares the change that must make it red.** Falsetto's own suite
runs in strict mode, so an undeclared check fails the build. If you cannot say what
change to the subject should make your check fail, the check is not finished.

## What a change carries

- Code with type annotations. `mypy --strict` is clean on `src/`.
- Formatting and lint by `ruff`. No exceptions without a comment saying why.
- A `CHANGELOG.md` entry under *Unreleased*.
- If the change touches an increment in `docs/plan.md`, the row's status.
- If the change alters behavior described in `docs/design.md`, that section.

## Commits and pull requests

Commit subjects are imperative. The body says why when the why is not obvious.
Contributions are accepted under the Apache License 2.0; by submitting one you
agree to its terms for your contribution, as its section 5 describes. No separate
agreement is needed.

## Reporting a bug

Open an issue with the smallest check that shows the problem and the verdict line
you got. A check that reports the wrong verdict is the most valuable report we can
receive.
