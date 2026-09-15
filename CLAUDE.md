# Falsetto: instructions for agent sessions

Read `README.md` for the thesis, `docs/design.md` for the shape, `docs/how-it-works.md` for
the execution path, `docs/plan.md` for the increment ledger. This file says how to work here.

## The one rule

Every check declares the change to the subject that must make it red. The repository runs
in strict mode, so an undeclared check fails the build. Before writing a check, answer
"what change should make this red?" in one sentence; that sentence is the declaration.
The change is to the subject, never to the check.

## Commands

```
uv sync                                   # environment with the dev tools
uv run pytest                             # own checks, strict; every one must be proven
uv run pytest examples/router             # must print: 1 proven, 1 failed, 1 false, 1 unproven
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

## Shape

- `src/falsetto/core.py` is the only place verdicts are computed, and it imports nothing
  from pytest. Front-ends adapt to it; they never re-implement the verdicts.
- `src/falsetto/plugin.py` is the pytest adapter. It runs whole protocols and observes
  reports; a declaration's change is applied before setup.
- `src/falsetto/patching.py`, `declaration.py` and `verdict.py` are runner-free.
- `examples/router/` is the README's example and is checked by the suite.

## Writing Falsetto's own checks

Declarations live in `tests/helpers.py` or next to the check, and they target the property
the check names: a check about the control run declares "no control run", not "everything
is proven". Three lessons the suite already paid for:

- Never patch the handle's own revert path (`Patch.undo`, `Patch.__exit__`) at class level;
  the outer handle then cannot revert, and every later run leaks. Rebind a module-level
  name the check reads instead.
- A conftest planted for a nested run must restore what it changes, in `pytest_unconfigure`.
- A check that falsifies a revert must reset its own subject: use a class defined inside the
  check, not a module-level one.
- A falsifier must change what the check observes. Under `--collect-only` nothing runs, so a
  falsifier that patches grading cannot bite; patch what the summary reads instead. A zero
  limit in a Python slice selects everything, so a "no evidence" falsifier needs an explicit
  branch in the code it falsifies.
- Under xdist, a falsifier patched in the controller does not reach the workers; falsify what
  the controller reads back.

## Each increment

1. Take the next row in `docs/plan.md`; its proving check is the definition of done.
2. Skeleton first: types and signatures compile before bodies are written.
3. Show the proving check go red for its stated reason before calling the row done.
4. Update the row's status, `CHANGELOG.md`, and any `docs/design.md` section the
   behavior touched.

## Style

Type-annotated, `mypy --strict` clean over `src`, `tests` and `examples`, `ruff` clean.
Default to no comments; add one only when the why is not obvious. Commit subjects are
imperative; bodies say why.
