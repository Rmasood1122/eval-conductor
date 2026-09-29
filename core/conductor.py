"""conductor — the 27-step build method as an enforcing CLI (eval-harness L7 asset).

A prompt advises; this refuses. Doctrine enforced in code:
  D1 week-one integrity: steps 1-6 (plus archetype promotions) must be done before
     any later step can be checked off.
  D2 evidence or it didn't happen: `check` requires a non-empty evidence string;
     ci/run-kind steps require something that looks like a run/commit reference.
  D6 disposition, never omission: all 27 rows always exist; defer needs --trigger,
     na needs --justify; steps marked never_na (T05, T27) cannot be na'd.
  D4/D8 sequence: `check` only closes the CURRENT applied step (deferred/na are
     skipped automatically); jumping ahead is refused with the doctrine line.
`audit` exits 1 on any violation -> wire it into CI like any other gate.

Usage (from the target project's repo root):
  python conductor.py init --project NAME --archetype A3 [--state PATH]
  python conductor.py status | guide | next | audit
  python conductor.py check --evidence "https://github.com/..../actions/runs/123"
  python conductor.py defer STEP --trigger "fires when ..."
  python conductor.py na STEP --justify "architecture reason ..."
  python conductor.py apply STEP        # re-activate a deferred/na row
State file: evals/conductor_state.json (override with --state). Commit it like code.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

import yaml

STEPS_FILE = Path(__file__).parent / "steps.yaml"
DEFAULT_STATE = Path("evals/conductor_state.json")

ARCHETYPES: dict[str, dict[str, Any]] = {
    # A1 deterministic pipeline (no LLM runtime)
    "A1": {"na": {17: "no autonomous actions: deterministic engine, no LLM at runtime",
                  11: "no LLM runtime -> no competing prompt variants"},
           "week_one_extra": []},
    # A2 RAG assistant
    "A2": {"na": {12: "LLM runtime is nondeterministic by design; noise bands from 5 baseline runs instead"},
           "week_one_extra": []},
    # A3 autonomous agent -> agent evals join week one
    "A3": {"na": {12: "LLM runtime is nondeterministic by design; noise bands from 5 baseline runs instead"},
           "week_one_extra": [17]},
    # A4 classifier/scoring service
    "A4": {"na": {}, "week_one_extra": []},
    # A5 human-reviewed content generator
    "A5": {"na": {}, "week_one_extra": []},
}

NEVER_NA_MSG = "REFUSED (doctrine): T05/T27 can never be N/A — an ungoverned instrument and an unaudited eval system are how eval theater survives."


def load_steps() -> list[dict[str, Any]]:
    steps = yaml.safe_load(STEPS_FILE.read_text(encoding="utf-8"))
    assert isinstance(steps, list) and len(steps) == 27, "steps.yaml must hold exactly 27 steps"
    return steps


def load_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        sys.exit(f"no state file at {path} — run `init` first")
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def corpus_by_step(steps: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {s["step"]: s for s in steps}


def week_one_set(state: dict[str, Any]) -> set[int]:
    return set(state["week_one"])


def current_step(state: dict[str, Any]) -> dict[str, Any] | None:
    """Open week-one applied steps first (archetypes can promote e.g. 17 into
    week one), then the remaining applied rows in step order."""
    w1 = set(state["week_one"])
    open_rows = [r for r in state["steps"]
                 if r["disposition"] == "applied" and r["status"] != "done"]
    for row in open_rows:
        if row["step"] in w1:
            return row
    return open_rows[0] if open_rows else None


# ---------------- commands ----------------

def cmd_init(args: argparse.Namespace) -> int:
    steps = load_steps()
    rows = []
    week_one = [s["step"] for s in steps if s.get("week_one")]
    na_map: dict[int, str] = {}
    for a in args.archetype:
        preset = ARCHETYPES.get(a)
        if preset is None:
            sys.exit(f"unknown archetype {a}; choose from {sorted(ARCHETYPES)}")
        na_map.update(preset["na"])
        week_one += preset["week_one_extra"]
    for s in steps:
        n = s["step"]
        if n in na_map and s.get("never_na"):
            print(f"note: archetype wanted step {n} N/A but it is never_na — kept applied")
            disposition, just = "applied", None
        elif n in na_map:
            disposition, just = "na", na_map[n]
        else:
            disposition, just = "applied", None
        rows.append({"step": n, "t": s["t"], "name": s["name"],
                     "disposition": disposition, "status": "pending",
                     "trigger_or_justification": just, "evidence": None, "closed": None})
    state = {"project": args.project, "archetypes": args.archetype,
             "created": date.today().isoformat(), "week_one": sorted(set(week_one)),
             "steps": rows, "doctrine_flags": [], "log": []}
    save_state(args.state, state)
    print(f"initialized {args.project} [{','.join(args.archetype)}] -> {args.state}")
    print(f"week-one steps (D1, non-negotiable): {state['week_one']}")
    return cmd_guide(args)


def cmd_status(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    cur = current_step(state)
    print(f"project: {state['project']}  archetypes: {state['archetypes']}")
    print(f"{'#':>3} {'T':<5} {'disposition':<11} {'status':<12} name")
    for r in state["steps"]:
        mark = "->" if cur and r["step"] == cur["step"] else "  "
        print(f"{mark}{r['step']:>2} {r['t']:<5} {r['disposition']:<11} {r['status']:<12} {r['name']}")
    done = sum(1 for r in state["steps"] if r["status"] == "done")
    print(f"\ndone {done}/27 · deferred {sum(1 for r in state['steps'] if r['disposition']=='deferred')}"
          f" · na {sum(1 for r in state['steps'] if r['disposition']=='na')}")
    if state["doctrine_flags"]:
        print("DOCTRINE FLAGS:", *state["doctrine_flags"], sep="\n  - ")
    return 0


def cmd_guide(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    cur = current_step(state)
    if cur is None:
        print("all applied steps done — run `audit`, then production loop (25-27) forever.")
        return 0
    s = corpus_by_step(load_steps())[cur["step"]]
    print(f"\n== STEP {s['step']} · {s['t']} — {s['name']} (phase {s['phase']}"
          + (", WEEK ONE" if s["step"] in week_one_set(state) else "") + ") ==")
    print(f"TOOLS : {s['tools']}")
    print(f"EXIT  : {s['exit']}")
    print(f"FAKE  : most common way this step is faked: {s['common_fake']}")
    print(f"CLOSE : conductor check --evidence '<{s['evidence_kind']}>'  (D2: no artifact, no advance)")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    cur = current_step(state)
    if cur is None:
        sys.exit("nothing to check — all applied steps are done")
    if args.step is not None and args.step != cur["step"]:
        sys.exit(f"REFUSED (D8 sequence): current step is {cur['step']} ({cur['name']}); "
                 f"step {args.step} cannot be closed before it. Use defer/na with a reason if it truly does not apply.")
    ev = (args.evidence or "").strip()
    if not ev or "..." in ev or "NNN" in ev or "<" in ev or ">" in ev or ev.lower() in ("todo", "tbd", "done"):
        sys.exit("REFUSED (D2): evidence or it didn't happen — pass --evidence with the artifact (CI run URL, file path, hash set, label export).")
    if len(ev) > 300:
        sys.exit("REFUSED (D2): evidence is suspiciously long — looks like pasted command text, not an artifact reference.")
    kind = corpus_by_step(load_steps())[cur["step"]]["evidence_kind"]
    if kind == "ci" and not re.search(r"https://github\.com/\S+/actions/runs/\d+", ev):
        sys.exit(f"REFUSED (D2): step {cur['step']} closes only on a real Actions run URL "
                 "(https://github.com/<owner>/<repo>/actions/runs/<id>).")
    # D1: no post-week-one step closes while a week-one applied step is open
    w1 = week_one_set(state)
    if cur["step"] not in w1:
        open_w1 = [r["step"] for r in state["steps"]
                   if r["step"] in w1 and r["disposition"] == "applied" and r["status"] != "done"]
        if open_w1:
            sys.exit(f"REFUSED (D1 week-one integrity): steps {open_w1} still open.")
    cur["status"] = "done"
    cur["evidence"] = ev
    cur["closed"] = date.today().isoformat()
    state["log"].append({"date": cur["closed"], "step": cur["step"], "evidence": ev,
                         "note": args.note or ""})
    save_state(args.state, state)
    print(f"step {cur['step']} DONE — evidence recorded: {ev}")
    return cmd_guide(args)


def _find(state: dict[str, Any], n: int) -> dict[str, Any]:
    for r in state["steps"]:
        if r["step"] == n:
            return r
    sys.exit(f"no step {n}")


def cmd_defer(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    if not (args.trigger or "").strip():
        sys.exit("REFUSED (D6): defer needs --trigger — a concrete, firable event. Deferred-forever is not a disposition.")
    if args.step_n in week_one_set(state):
        sys.exit("REFUSED (D1): week-one steps cannot be deferred.")
    r = _find(state, args.step_n)
    r["disposition"], r["trigger_or_justification"] = "deferred", args.trigger
    save_state(args.state, state)
    print(f"step {args.step_n} DEFERRED — fires when: {args.trigger}")
    return 0


def cmd_na(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    s = corpus_by_step(load_steps())[args.step_n]
    if s.get("never_na"):
        sys.exit(NEVER_NA_MSG)
    if not (args.justify or "").strip():
        sys.exit("REFUSED (D6): na needs --justify — a justification tied to the architecture that survives challenge.")
    if args.step_n in week_one_set(state):
        sys.exit("REFUSED (D1): week-one steps cannot be N/A.")
    r = _find(state, args.step_n)
    r["disposition"], r["trigger_or_justification"] = "na", args.justify
    save_state(args.state, state)
    print(f"step {args.step_n} N/A — {args.justify}")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    r = _find(state, args.step_n)
    r["disposition"], r["trigger_or_justification"] = "applied", None
    if r["status"] == "done" and not r["evidence"]:
        r["status"] = "pending"
    save_state(args.state, state)
    print(f"step {args.step_n} re-activated (applied)")
    return 0


def cmd_reopen(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    r = _find(state, args.step_n)
    if r["status"] != "done":
        sys.exit(f"step {args.step_n} is not done — nothing to reopen")
    state["log"].append({"date": date.today().isoformat(), "step": args.step_n,
                         "evidence": "", "note": f"REOPENED (was: {r['evidence']}) {args.reason or ''}"})
    r["status"], r["evidence"], r["closed"] = "pending", None, None
    save_state(args.state, state)
    print(f"step {args.step_n} REOPENED — prior evidence voided, logged")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    steps = corpus_by_step(load_steps())
    violations: list[str] = []
    if len(state["steps"]) != 27:
        violations.append(f"V3: {len(state['steps'])} rows, must be 27 — silent gap")
    for r in state["steps"]:
        s = steps.get(r["step"], {})
        if r["disposition"] == "deferred" and not (r["trigger_or_justification"] or "").strip():
            violations.append(f"V3: step {r['step']} deferred without trigger")
        if r["disposition"] == "na":
            if not (r["trigger_or_justification"] or "").strip():
                violations.append(f"V3: step {r['step']} na without justification")
            if s.get("never_na"):
                violations.append(f"V3: step {r['step']} ({s['t']}) is never_na but marked na")
        if r["status"] == "done" and not (r["evidence"] or "").strip():
            violations.append(f"D2: step {r['step']} done without evidence")
    w1 = week_one_set(state)
    w1_open = [r["step"] for r in state["steps"]
               if r["step"] in w1 and r["disposition"] == "applied" and r["status"] != "done"]
    later_done = [r["step"] for r in state["steps"] if r["step"] not in w1 and r["status"] == "done"]
    if w1_open and later_done:
        violations.append(f"D1: steps {later_done} closed while week-one {w1_open} still open")
    if violations:
        print("AUDIT: BLOCK")
        for v in violations:
            print("  -", v)
        return 1
    done = sum(1 for r in state["steps"] if r["status"] == "done")
    print(f"AUDIT: PASS — {done}/27 done, dispositions complete, evidence present, week-one intact")
    return 0


def cmd_next(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    cur = current_step(state)
    if cur is None:
        print("next: run `audit`; then the forever loop (steps 25-27) on schedule.")
    else:
        s = corpus_by_step(load_steps())[cur["step"]]
        print(f"next: step {cur['step']} ({s['name']}) — close it with: {s['exit']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="conductor", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--state", type=Path, default=DEFAULT_STATE)
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("init"); sp.add_argument("--project", required=True)
    sp.add_argument("--archetype", action="append", default=[], choices=sorted(ARCHETYPES))
    sp.set_defaults(fn=cmd_init)
    for name, fn in (("status", cmd_status), ("guide", cmd_guide),
                     ("audit", cmd_audit), ("next", cmd_next)):
        sub.add_parser(name).set_defaults(fn=fn)
    sp = sub.add_parser("check"); sp.add_argument("--evidence", required=False)
    sp.add_argument("--note"); sp.add_argument("--step", type=int, default=None)
    sp.set_defaults(fn=cmd_check)
    sp = sub.add_parser("defer"); sp.add_argument("step_n", type=int)
    sp.add_argument("--trigger"); sp.set_defaults(fn=cmd_defer)
    sp = sub.add_parser("na"); sp.add_argument("step_n", type=int)
    sp.add_argument("--justify"); sp.set_defaults(fn=cmd_na)
    sp = sub.add_parser("apply"); sp.add_argument("step_n", type=int)
    sp.set_defaults(fn=cmd_apply)
    sp = sub.add_parser("reopen"); sp.add_argument("step_n", type=int)
    sp.add_argument("--reason"); sp.set_defaults(fn=cmd_reopen)
    args = p.parse_args(argv)
    # argparse global --state must be visible after subparser: re-bind default
    if not hasattr(args, "state"):
        args.state = DEFAULT_STATE
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
