# Changelog

All notable changes to Falsetto are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project follows
[Semantic Versioning](https://semver.org/) once it reaches 0.1.0.

## [Unreleased]

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
  not-applied, wrong-reason, not-repeatable, internal-error.
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

### Changed
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
