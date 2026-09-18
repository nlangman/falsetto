# Changelog

All notable changes to Falsetto are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project follows
[Semantic Versioning](https://semver.org/) once it reaches 0.1.0.

## [Unreleased]

[Unreleased]: https://github.com/nlangman/falsetto/commits/main

### Added
- The declaration: `must_fail_when(change, *, expect=None, describe=None, scope="function")`,
  with Falsetto's own patching handle (`Patch`) and a visible expectation in reports.
- The runner-agnostic core: `check_callable`, `check`, `prove`, `run_callable`, `RunResult`.
  It imports nothing from pytest.
- The pytest adapter: whole-protocol negative and control runs, verdicts as native categories,
  false and strict-unproven checks as real failures, the verdict line with its denominator,
  hints, `--falsetto`, `--falsetto-strict`, `--falsetto-json`, the `falsetto` and
  `falsetto_strict` ini keys, and the `no_proof` marker.
- Verdict records on `user_properties` as JSON, so they survive xdist and appear in JUnit.
- Reason codes on every verdict: stated-reason, positive-failed, negative-passed, undeclared,
  not-applied, not-reverted, wrong-reason, not-repeatable, internal-error.
- The router example with one check per verdict.
- A prior-art page: spec-verify, pytest-mutagen, extreme mutation, and the wider field.
- Apache License 2.0.

- `scope=` on the declaration: the fixture scopes rebuilt under the change, and the teardown
  boundary for every run of the check.
- Reason codes out-of-scope and misconfigured; evidence (the deciding run's failure text) on
  every verdict record and in the summary.
- Coverage measurement is paused during the control and negative runs.
- A warning at startup naming plugins that also implement the run protocol.
- `--falsetto-controls` and the `falsetto_controls` ini key: the number of control runs.
- `scope="package"`; `complete` and `stopped` in the JSON report.

### Fixed
- The scope guard no longer suppresses a failure of the fixture manager it asks about
  dynamically reached fixtures. A lookup that raises is an internal error, which fails the
  build and asks for a report, rather than a fixture silently not counted and a check
  reported false that Falsetto could not grade.
- The pytest requirement is bounded, `pytest>=8.0,<10`: the plugin imports the run protocol
  from `_pytest` on every pytest run, so a pytest that moves it must be an install failure
  rather than an import error in an unrelated suite.
- A `falsetto.verdict` property is validated before it is read: a record whose verdict or
  reason is not one of Falsetto's is ignored, rather than counted or crashed on in the
  summary. A well-formed record on an item Falsetto did not grade is still taken at face
  value; the design record says so.
- `core.evidence` is public and the pytest adapter calls it instead of slicing for itself,
  so an empty evidence limit keeps nothing on both paths rather than everything on one.
- A declared change whose undo raises is the verdict not-reverted, which always fails the build
  and stops the session, rather than an internal error reported as a bug in Falsetto while every
  later check runs against a subject that is still patched.
- Locations in reports are relative to the working directory when the file is inside it, so a
  report does not carry the machine it ran on.
- A malformed `falsetto_controls` ini value is read only when Falsetto is enabled, and is a
  usage error rather than a crash inside `pytest_configure`.
- An interrupt raised by one undo step no longer strands the remaining ones: every step runs,
  and the interrupt is raised afterwards, ahead of any ordinary error.
- An interrupt raised by one undo step no longer drops what another step raised with it. The
  first ordinary error becomes the interrupt's `__context__`, so a traceback still names
  everything that went wrong while the subject was being put back.
- An undo step that raises something outside the passthrough set that is not an `Exception` is
  the verdict not-reverted, like every other undo that failed, rather than an internal error
  reported as a bug in Falsetto while every later check runs against a subject that is still
  patched. The catch that applies a declared change and the catch that undoes it are now the
  same width.
- A check can no longer forge a verdict for itself by recording a `falsetto.verdict` property.
  Every entry under one of Falsetto's own names is stripped from a report as it is made, on
  whichever process ran the item, and Falsetto appends its own afterwards and only for an item
  it graded. This closes the case the design record carried as an open limit, an item Falsetto
  did not grade and so had no record of its own to win with, and it needs no secret crossing the
  xdist boundary. A record a test wrote under those names is dropped rather than renamed, so it
  no longer reaches JUnit output; a name outside the `falsetto.` prefix is untouched.
- A `Reason` with no sentence in `MESSAGES` is refused when `falsetto.verdict` loads, rather
  than a `KeyError` raised while a report is written, on the failure path, long after the
  reason was added. `MESSAGES` and `HINTS` are read-only mappings.
- A declaration's description and expectation, and an internal error's traceback, are bounded
  before they reach a report.

### Changed
- The JSON report carries `schema: 1`, the run's context (`rootdir`, `args`, `strict`, `controls`,
  `pytest`, `python`, `started`, `finished`) and `fails_build` on every record; `totals` keeps
  verdict counts and status counts apart as `verdicts` and `statuses`.
- After review round one the negative run became a whole fresh protocol with the change
  applied before setup, and proven now requires a passing control run. The own-frame rule
  on assertions was dropped; `pytest.fail` counts as the stated reason by default.
- After review round two the control run precedes the negative run, every run of a check
  tears down to the declaration's boundary rather than to the session's next item, proven
  and non-strict unproven keep pytest's `passed` category, the verdict line says "failed as
  written", the verdict record is namespaced and read last-wins, a `no_proof` marker needs a
  reason and is listed, and strict mode fails any session that graded nothing.
- After review round three the scope guard reads every fixture the check used by any route
  and ignores fixtures pytest or installed plugins define; out-of-scope and misconfigured
  verdicts fail the build; class attributes are restored as the descriptors they were; a
  post-grading teardown failure is merged into the check's own teardown report; the
  debugger plugins are paused during graded runs; an unwritable JSON report is an
  internal-error exit.
