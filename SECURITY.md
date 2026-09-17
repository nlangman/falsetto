# Security

Falsetto runs a declared test three times and patches your code in-process during the
third run. It never edits your code or your tests on disk; the only file it writes is
the report you ask for with `--falsetto-json`. It never executes anything it did not
receive from your own test suite. Still, a bug that made the negative run escape its
scope would be a security matter, and we treat it as one.

## Reporting

Use GitHub's private vulnerability reporting on this repository (Security → Report a
vulnerability). Please do not open a public issue for a suspected vulnerability. You
will get an acknowledgement within a week and a fix or a plan within thirty days.

## Supported versions

Pre-alpha. Fixes land on `main` and ship in the next release; there are no backports.

| Version | Supported |
|---|---|
| the latest 0.0.x release | yes |
| `main` | yes |
| anything older | no |
