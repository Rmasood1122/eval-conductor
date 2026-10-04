# We p-hacked our own eval gate on purpose. Here's the receipt that caught it.

Teams gate AI releases on evals now. A number comes out of a test run — a pass
rate, an accuracy, a judge score — and if it clears a threshold, you ship.

There's a hole in that, and it isn't the one people guard. Everyone worries the
*number* is wrong. Almost nobody guards the *bar*. The bar is just a line in a
config file, and you usually write it **after** you've already seen the number.

That's p-hacking — the same move that rots published science: run the experiment,
see the result, then pick the threshold the result happens to clear. The pass rate
is real. The bar is fiction, reverse-engineered from the answer you wanted.

We build an eval gate for a living. So we tried to cheat our own.

## The setup

Seal a strict bar before running anything — 90% pass rate, hard block:

```
$ prereg.py seal --registry registry.yaml
sealed [signed]: evals/seals/2026-10-04/e5588e36-….json
Commit and push it NOW — a local-only seal is a claim, not evidence.
```

Then run a candidate that comes in **under** the bar — 87%:

```
$ promote.py --registry registry.yaml --candidate candidate.json
DECISION: BLOCK
```

Correct. 0.87 < 0.90, the gate blocks, nothing ships. This is where an honest
engineer stops and fixes the regression.

## The cheat

Instead, do what a tired engineer does at 2am against a deadline: open
`registry.yaml`, change one number — `0.90` → `0.85` — so 87% clears. Re-run:

```
$ promote.py --registry registry.yaml --candidate candidate.json
DECISION: PROMOTE
PRE-REG: the registry drifted from the sealed bar — this decision was NOT made
under the pre-committed registry. Run 'prereg.py check --require-seal' to enforce.
```

The gate said PROMOTE — the bar moved, so technically it passes — **but it knew the
bar had moved since it was committed to.** The enforcement check makes that fatal:

```
$ prereg.py check --require-seal
PRE-REG DRIFT: seal e5588e36…; registry DRIFTED; bands MATCH — the bar changed
since it was sealed. The decision is NOT being made under the pre-committed registry.
  registry.yaml differs byte-for-byte from the sealed copy. If the change is
  legitimate, seal again BEFORE re-running the candidate — never after seeing its scores.
exit code: 2
```

In CI, exit 2 fails the build. The cheat doesn't ship.

## The part that matters: the receipt remembers

A drift warning you can ignore. What you can't ignore is that the *proof of the
decision* recorded the cheat, permanently, inside itself. The actual receipt the
PROMOTE emitted:

```json
"decision": "PROMOTE",
"prereg": {
  "sealed": true,
  "seal_id": "e5588e36-…",
  "registry_match": false,
  "bands_match": true,
  "signature_ok": true,
  "chain_ok": true
}
```

`registry_match: false`. The signed, tamper-evident receipt that says "this passed"
also says, in the same breath, "…under a bar that drifted from the one I
pre-committed." You cannot have the green without the asterisk. And the receipt
chain still verifies clean — we didn't break it, we got *caught* by it:

```
$ eval_receipt.py verify
chain OK — decisions unaltered since signing. exit 0
```

Three controls, composed, closed the hole:

- a **diff-lint** proves the registry didn't get weaker than its git base;
- **pre-registration** proves the bar was fixed *before* the result existed;
- a **tamper-evident receipt** carries both verdicts, un-rewritable.

No eval tool we know of — MLflow, LangSmith, Braintrust — records *when the bar was
fixed relative to the run*. That's the question this is built around.

## This isn't the first time it caught us

The honest reason we built the pre-registration piece: the gate had already caught
us once. While building the 27-step evidence ledger, it logged a build step being
closed on placeholder evidence — three separate times — and refused each. Those
refusals are still in the committed ledger. We didn't scrub them, because a tool
whose whole pitch is "prove it, don't trust it" doesn't get to hide the time it
caught its own maker. That's the feature, not the bug.

## What this does NOT prove

Overselling it would be the exact sin this is against:

- A seal proves the bar is byte-identical to what was sealed, and — because it's
  committed and pushed — that it was fixed before the result, witnessed by git
  history anyone can read. It does **not** prove the bar was *strict enough*. A
  pre-committed weak bar is still weak; strictness is the reviewer's job.
- The signing is a shared-secret HMAC. It proves a decision is unaltered since
  signing under a key your team controls; it does **not** identify who signed, and a
  key-holder could backdate the seal's timestamp. That's why the real defense is
  distribution — a seal in pushed history a third party saw — not the clock.
- A green badge from the quick version proves "not worse than before," not "good."
  Three trivial tests, proven, is still three trivial tests — which is why the badge
  always shows the count.

## Try it in 60 seconds

The full gate is a plugin. The fastest way to feel it is one command on a repo you
already have, no config:

```
/eval-prove
```

It runs your existing tests, emits a signed receipt that they passed at this commit,
and hands you a badge to paste in a PR. The first run sets your bar; a later run
that quietly drops the pass rate or deletes tests gets blocked. You don't have to
trust that your evals are honest. You can prove it — or get caught.

---

*[Eval Conductor](https://github.com/Rmasood1122/eval-conductor) is open source
(MIT). The thesis: trust an AI verdict only by what it can prove.*
