# Security

Falsetto runs your tests twice and patches your code in-process during the second
run. It never edits files on disk and never executes anything it did not receive
from your own test suite. Still, a bug that made the negative run escape its scope
would be a security matter, and we treat it as one.

## Reporting

Use GitHub's private vulnerability reporting on this repository (Security → Report a
vulnerability). Please do not open a public issue for a suspected vulnerability. You
will get an acknowledgement within a week and a fix or a plan within thirty days.

## Supported versions

Pre-alpha: only the `main` branch is supported.
