# Changelog

All notable changes to Falsetto are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project follows
[Semantic Versioning](https://semver.org/) once it reaches 0.1.0.

## [Unreleased]

### Added
- The declaration: `must_fail_when(change, *, expect=AssertionError, describe=None)`.
- The runner-agnostic core: `falsetto.core.prove` and `falsetto.core.check`.
- The pytest adapter: verdicts as native categories (proven, false, unproven), the
  verdict line, hints for non-green verdicts, and `--falsetto-strict`.
- Verdict records on `user_properties`, so they survive serialization and appear in
  JUnit output.
- The router example with one check per verdict.
- Apache License 2.0.
- A prior-art page: spec-verify, pytest-mutagen, extreme mutation, and the wider field.
