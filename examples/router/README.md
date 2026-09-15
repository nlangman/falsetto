# The router example

Four checks, one per verdict. From the repository root:

```
pytest examples/router --falsetto
```

Expected verdict line:

```
falsetto: 1 proven, 1 failed, 1 false, 1 unproven (4 graded of 4 run)
```

Each check's comment says which verdict it earns and why. Inside this repository the
`falsetto_strict` setting also applies, so the unproven check fails the build here; that is
the repository's own standard, not a property of the example.
