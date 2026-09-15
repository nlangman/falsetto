# Falsetto: instructions for agent sessions

Read `README.md` for the thesis, `docs/design.md` for the shape, `docs/plan.md` for the
increment ledger. This file says how to work here.

## The one rule

Every check declares the change to the subject that must make it red. The suite runs
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

- `src/falsetto/core.py` is the only place verdicts are computed. Front-ends adapt to
  it; they never re-implement the four states.
- `src/falsetto/plugin.py` is the pytest adapter. pytest performs the positive run.
- `src/falsetto/declaration.py` and `verdict.py` are runner-free.
- `examples/router/` is the README's example and is checked by the suite.

## Each increment

1. Take the next row in `docs/plan.md`; its proving check is the definition of done.
2. Skeleton first: types and signatures compile before bodies are written.
3. Show the proving check go red for its stated reason before calling the row done.
4. Update the row's status, `CHANGELOG.md`, and any `docs/design.md` section the
   behavior touched.

## Style

Type-annotated, `mypy --strict` clean, `ruff` clean. Default to no comments; add one
only when the why is not obvious. Commit subjects are imperative; bodies say why.
