# Changelog

All notable changes to Falsetto are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project follows
[Semantic Versioning](https://semver.org/) once it reaches 0.1.0.

## [Unreleased]

### Added
- The declaration: `must_fail_when(change, *, expect=None, describe=None)`, with Falsetto's
  own patching handle (`Patch`) and a visible expectation in reports.
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

### Changed
- After review round one the negative run became a whole fresh protocol with the change
  applied before setup, and proven now requires a passing control run. The own-frame rule
  on assertions was dropped; `pytest.fail` counts as the stated reason by default.
