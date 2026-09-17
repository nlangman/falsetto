# Prior art

What came before Falsetto, what each thing does, and where Falsetto differs. Written
2026-09-14. The verification status of each entry is at the end, because a prior-art
page that overstates its own certainty would be the kind of claim this project exists
to catch.

## The nearest neighbours

### spec-verify (2026)

A Claude Code skill by Daniel Nwaneri, described in
[How to stop letting AI agents fake their own tests](https://www.freecodecamp.org/news/how-to-stop-letting-ai-agents-fake-their-own-tests/)
(freeCodeCamp, 2026-08-26; repository at
[github.com/dannwaneri/spec-verify](https://github.com/dannwaneri/spec-verify)).
For each acceptance criterion it performs one targeted mutation, informed by the
criterion's stated assumption, and runs the criterion's test against the mutant. It has
four verdicts: `VERIFIED` (the test fails on the mutant and passes on the real code),
`VACUOUS` (the test passes either way), `BROKEN-TEST` (the test does not even confirm
the current behaviour), and `UNVALIDATABLE` (no safe mutation exists), the last waivable
only by an on-record human sign-off.

This is the closest thing in spirit. Its `VACUOUS` is Falsetto's **false**. The
differences are in where the mechanism lives and what it covers:

- spec-verify is a workflow inside an agent session, driven by a spec. Falsetto is a
  test-runner plugin with a runner-agnostic core, driven by the tests themselves, and
  runs in CI without any agent present.
- spec-verify's unit is the acceptance criterion. Falsetto's unit is the check, and the
  declaration is mandatory: in strict mode an undeclared check fails the build.
- The verdicts are close cousins (`VERIFIED`, `VACUOUS` and `BROKEN-TEST` map onto
  Falsetto's **proven**, **false** and **failed**), but Falsetto reports them as native
  runner outcomes, adds **unproven** for a check that declares nothing, caches proofs,
  and extends the same rule to evals.

### pytest-mutagen (2020)

[pytest-mutagen](https://pypi.org/project/pytest-mutagen/) (version 1.3, released
2020-07-24; Timothée Paquatte and Harrison Goldstein, described in
[Testing your tests](https://www.cis.upenn.edu/~plclub/blog/2020-05-29-mutagen/))
lets you declare mutants by hand: `@mg.mutant_of` replaces a whole function,
`@mg.has_mutant` and `mg.mut(...)` swap an expression inline. pytest then runs the
suite against each mutant and, with `--mutagen-stats`, reports how many tests caught
each one.

The mechanism, hand-written mutants applied in-process during a pytest run, is the
nearest implementation precedent. The differences:

- Mutants belong to files or functions and apply to every test in the files they are
  linked to, which for `@mg.has_mutant` is every collected file by default. Falsetto's
  declaration belongs to one check.
- The report is per mutant: killed or survived. Falsetto's verdict is per check, and
  it has states a kill count cannot express: **false** (this check cannot fail) and
  **unproven** (nothing is known about this check).
- Mutagen has not been released since 2020.

### Extreme mutation and pseudo-tested methods (2016 onward)

[Niedermayr, Juergens and Wagner (2016)](https://arxiv.org/abs/1611.07163) introduced
extreme mutation: delete a covered method's whole body, or replace it with a trivial
return, and see whether any test fails. A method the suite executes but whose removal
changes no test outcome is *pseudo-tested*.
[Descartes](https://github.com/STAMP-project/pitest-descartes) (Vera-Pérez and others,
2018; a PIT engine for Java) automates it; Reneri turns its findings into suggestions;
[PseudoSweep](https://philmcminn.com/publications/maton2024b.pdf) (Maton, Kapfhammer
and McMinn, 2024) extends it to statements. The 2016 paper found pseudo-tested methods
common: a mean of 11.41% of methods under unit tests and 35.48% under system tests
across its study objects, with far more spread among the system-test suites.

Pseudo-testedness is the method-level cousin of Falsetto's **false**: the suite ran the
code and never checked its effect. The differences: extreme mutation is automatic and
coarse, and it grades methods and suites. Falsetto's change is declared, specific, and
grades one check.

## The wider field

- **Whole-program mutation testing.** [mutmut](https://github.com/boxed/mutmut),
  [cosmic-ray](https://github.com/sixty-north/cosmic-ray),
  [mutatest](https://mutatest.readthedocs.io/),
  [pytest-gremlins](https://github.com/mikelane/pytest-gremlins) for Python;
  [Stryker](https://stryker-mutator.io/), [PIT](https://pitest.org/) elsewhere. They
  generate many mutants across a codebase and report a kill ratio. The unit is the
  mutant; a surviving mutant means some test is missing, not that a named test is
  wrong. Falsetto is complementary: one intended mutant per check, two runs per check,
  and a verdict per check. pytest-gremlins also caches results by content hash, which
  is the same idea as Falsetto's proof cache.
- **Mutation feedback for test generation.** MuTAP, MutGen,
  [ACH at Meta](https://arxiv.org/abs/2501.12862) (2025) and
  [PRIMG](https://arxiv.org/abs/2505.05584) (2025) feed undetected or surviving mutants
  back into a language model so it generates stronger tests. They improve generation;
  they do not attach a declared change to each test.
- **Assertion presence checks.** Jest's `expect.hasAssertions()` and
  `expect.assertions(n)`, the `jest/expect-expect` lint rule,
  [pytest-smell](https://pypi.org/project/pytest-smell/) and tsDetect detect tests
  that reach no assertion or look suspicious. They answer "did an assertion run?";
  Falsetto answers "can this assertion fail?".
- **Evidence that the problem is real.** A 2026 study of workflows in which both the
  code and its tests are generated by language models,
  [How effective are traditional test criteria at detecting bugs in large language
  models generated code?](https://arxiv.org/abs/2609.09315), distinguishes *fault
  triggering* (the test executes the faulty code) from *fault detection* (the test
  fails because of it) and reports detection rates near zero even where faults are
  triggered, because the oracles do not capture the faulty behaviour. A test that
  triggers a fault and passes is exactly a **false** check.

## A vocabulary map

| Falsetto | Mutation testing | Pseudo-testedness |
|---|---|---|
| proven | the declared mutant is killed by this check | the effect is checked |
| false | the declared mutant survives this check | pseudo-tested, at check level |
| unproven | no mutant declared for this check | no data |
| failed | the original test fails | not applicable |

## What Falsetto adds

Not the mechanism, which pytest-mutagen had in 2020, and not the observation, which
the pseudo-testedness literature made a decade ago. The combination:

1. **Ownership.** The declaration belongs to the check, and it is mandatory under
   strict mode. A suite cannot be green with an unproven check in it.
2. **A per-check verdict as a native runner outcome**, including **unproven** for a
   check that declares nothing, so "this specific check is wrong" is a build result,
   not a metric.
3. **One core, many front-ends.** The verdict logic is runner-agnostic; the pytest
   plugin is an adapter, and a bespoke harness or a port calls the same functions.
4. **Evals under the same rule.** A judge that scores garbage high is a false eval.

## Verification status

- Every entry was re-read against its primary source on 2026-09-17, before the first
  public release: the linked repositories, documentation pages and papers themselves.
  The figures quoted above are taken from the papers, not from summaries of them.
- Corrections made in that pass: spec-verify's full verdict set, pytest-mutagen's
  mutant scoping, the PseudoSweep author list, the source and meaning of the
  pseudo-tested figures, and one tool ("GEM") removed from the mutation-feedback entry
  because no such tool doing that work could be found.
