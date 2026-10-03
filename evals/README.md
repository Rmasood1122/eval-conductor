# eval-conductor runs on itself

Two suites live here. The case directories (`refuses-threshold-edit/`,
`installs-gate/`, `nan-must-block/`) are a native `claude plugin eval` suite —
run `claude plugin eval .` from the plugin root; results land in `results/`
(gitignored). The rest of this file describes the second suite: the gate
applied to this repository's own test run.

This directory is eval-conductor's own release gate — the tool applied to the
tool. It is here so the project does not just preach fail-closed gating; it is
subject to it on every CI run.

Because this repo is a deterministic Python tool, not an LLM system, the
metrics are not faked model-quality scores. They gate the repo on its own
doctrine, measured by `run_self_eval.py`:

| metric | meaning | blocks on |
|---|---|---|
| `self_test_pass_rate` | fraction of the test suite that passes | any failing test |
| `test_count` | total collected tests | a test being silently deleted |
| `fail_closed_tests_covered` | tests asserting BLOCK/REFUSED/non-zero exit | a protection test being removed |

All three are `hard`. Thresholds are the counts measured when the registry was
committed. Changing a threshold requires a written reason in
`registry_changes.yaml`; `registry_diff_lint.py` enforces that in CI.

## Run it locally

```
python evals/run_self_eval.py        # writes evals/candidate.json
python core/promote.py --registry evals/registry.yaml \
                       --candidate evals/candidate.json \
                       --baseline evals/baseline.json    # exit 0 = PROMOTE
```

`baseline.json` is optional — without it the gate judges thresholds only, which
is the mode CI uses. `candidate.json` and `baseline.json` are generated
artifacts and are gitignored.

## Honest limits

`fail_closed_tests_covered` counts tests by a text pattern
(`run_self_eval.py :: FAIL_CLOSED`). It is reproducible run to run, but a
large test refactor can legitimately move the number. When that happens the
fix is to adjust the threshold **with a justification** — not to route around
the gate. That governance is the point: the number cannot drop silently.

This gate proves our tests pass and our protection isn't quietly removed. It
does not prove the tests are *good* — that is what review is for.
