"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, aggregate, load_spec, per_item
from lab9.graders import GRADERS


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    graded = [m["id"] for m in spec["metrics"] if m["id"] in GRADERS]
    for who, rep in (("PR", pr), ("baseline", base)):
        problems += [f"{who}: {p}" for p in _report_problems(rep, spec, graded)]
    # Same (item, seed) set as the baseline: no cherry-picked seeds/items, nothing added.
    pr_keys, base_keys = _keys(pr), _keys(base)
    if pr_keys != base_keys:
        miss, extra = sorted(base_keys - pr_keys, key=str), sorted(pr_keys - base_keys, key=str)
        problems.append(f"(item, seed) set differs from the baseline: {len(miss)} missing {miss[:3]}, "
                        f"{len(extra)} extra {extra[:3]}")
    seeds = sorted(spec.get("seeds") or [])
    for who, rep in (("PR", pr), ("baseline", base)):
        if seeds and sorted(rep["manifest"].get("seeds") or []) != seeds:
            problems.append(f"{who}: manifest seeds {rep['manifest'].get('seeds')} != spec seeds {seeds}")
        row_seeds = sorted({r.get("seed") for r in rep["rows"]}, key=str)
        if seeds and row_seeds != sorted(seeds, key=str):
            problems.append(f"{who}: row seeds {row_seeds} != spec seeds {seeds}")
    # Slice tags come from the label, never from the PR: relabelling hides a regression from the slice gate.
    pr_tags, base_tags = _slice_tags(pr), _slice_tags(base)
    changed = sorted(i for i in pr_tags.keys() & base_tags.keys() if pr_tags[i] != base_tags[i])
    if changed:
        problems.append(f"slice tags differ from the baseline for {len(changed)} item(s), e.g. {changed[0]}: "
                        f"{sorted(pr_tags[changed[0]])} vs {sorted(base_tags[changed[0]])}")
    problems += _against_eval_set(pr, base, spec)
    if base_spec is not None:
        problems += _ratchet(spec, base_spec)
    return problems


def _against_eval_set(pr: dict, base: dict, spec: dict) -> list[str]:
    """Both reports vs the eval set file in this checkout: the sha they claim, the items it holds and the slice
    tags it gives each item. Catches a PR and a baseline edited the same way (they would agree with each other)."""
    path = Path(spec.get("eval_set") or "")
    if not spec.get("eval_set") or not path.is_file():
        return []
    from lab9 import evalset
    sha = evalset.sha12(path)
    items = {it["item_id"]: frozenset(it.get("slices") or []) for it in evalset.load_jsonl(path)}
    out = []
    for who, rep in (("PR", pr), ("baseline", base)):
        if rep["manifest"].get("eval_set_sha") != sha:
            out.append(f"{who}: eval_set_sha {rep['manifest'].get('eval_set_sha')} != {path} ({sha})")
        got = {r.get("item_id") for r in rep.get("rows") or []}
        if got != set(items):
            out.append(f"{who}: items differ from {path}: {len(set(items) - got)} missing, {len(got - set(items))} unknown")
        tags = _slice_tags(rep)
        wrong = sorted(i for i in tags.keys() & items.keys() if tags[i] != items[i])
        if wrong:
            out.append(f"{who}: slice tags of {len(wrong)} item(s) differ from {path}, e.g. {wrong[0]}")
    return out


def _keys(rep: dict) -> set[tuple[str, int]]:
    return {(r.get("item_id"), r.get("seed")) for r in rep.get("rows") or []}


def _slice_tags(rep: dict) -> dict[str, frozenset[str]]:
    tags: dict[str, set[frozenset[str]]] = {}
    for r in rep.get("rows") or []:
        tags.setdefault(r.get("item_id"), set()).add(frozenset(r.get("slices") or []))
    # an item tagged differently on two of its own rows is itself a tampering sign: keep it distinguishable
    return {i: next(iter(v)) if len(v) == 1 else frozenset({"<inconsistent>"}) for i, v in tags.items()}


def _report_problems(rep: dict, spec: dict, graded: list[str]) -> list[str]:
    """Checks one report against itself: every one must hold for a report the eval script wrote untouched."""
    out: list[str] = []
    rows, man = rep.get("rows") or [], rep.get("manifest") or {}
    if rep.get("evaluator_failures"):
        out.append(f"{len(rep['evaluator_failures'])} evaluator failure(s), first: {rep['evaluator_failures'][0]}")
    for k, v in (rep.get("metrics") or {}).items():
        if isinstance(v, float) and not math.isfinite(v):
            out.append(f"metric {k} is {v}")
    keys = [(r.get("item_id"), r.get("seed")) for r in rows]
    dup = len(keys) - len(set(keys))
    if dup:
        out.append(f"{dup} duplicated (item, seed) row(s)")
    want_rows = (man.get("items") or 0) * len(man.get("seeds") or [])
    if len(rows) != want_rows:
        out.append(f"{len(rows)} rows != manifest {man.get('items')} items x {len(man.get('seeds') or [])} seeds")
    if len({k[0] for k in keys}) != man.get("items"):
        out.append(f"{len({k[0] for k in keys})} distinct items in rows != manifest items {man.get('items')}")
    bad = [(r.get("item_id"), r.get("seed"), m) for r in rows for m in graded if not isinstance(r.get(m), bool)]
    if bad:
        out.append(f"{len(bad)} row value(s) of a graded metric are missing/None/non-bool, e.g. {bad[0]}")
    # Metrics must be what the rows say: catches hand-edited numbers and rows removed after aggregation.
    if rows and not bad:
        have = rep.get("metrics") or {}
        try:
            again = aggregate([{"cost": 0.0, **r} for r in rows], [m for m in graded if m in have],
                              k_values=spec.get("pass_k", []))
        except Exception as exc:                      # malformed rows: untrusted by definition
            out.append(f"metrics cannot be recomputed from rows: {exc!r}")
        else:
            for k in sorted(have.keys() & again.keys()):
                if k == "cost_per_success" and any("cost" not in r for r in rows):
                    continue                          # cost is not a row column in this report
                if not _close(have[k], again[k]):
                    out.append(f"metric {k}={have[k]} but the rows give {again[k]}")
    return out


def _close(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool) or isinstance(b, bool) or not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        return a == b
    return math.isfinite(a) and abs(a - b) <= 1e-9


def _looser(th: dict, base_th: dict) -> list[str]:
    out = []
    for key in ("max", "max_increase"):
        if key in base_th and (key not in th or th[key] > base_th[key]):
            out.append(f"{key} {base_th[key]} -> {th.get(key, 'removed')}")
    if "min" in base_th and ("min" not in th or th["min"] < base_th["min"]):
        out.append(f"min {base_th['min']} -> {th.get('min', 'removed')}")
    if base_th.get("no_significant_drop") and not th.get("no_significant_drop"):
        out.append("no_significant_drop dropped")
    return out


def _ratchet(spec: dict, base_spec: dict) -> list[str]:
    """Same eval-set version => thresholds may only get stricter. A new version starts fresh (new baseline)."""
    out: list[str] = []
    if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
        if spec.get("eval_set") == base_spec.get("eval_set") and spec.get("labels") == base_spec.get("labels"):
            out.append(f"eval_set_version {base_spec.get('eval_set_version')} -> {spec.get('eval_set_version')} "
                       "but the eval set and labels are the same files: a version bump cannot reset the ratchet")
        return out
    for key in ("eval_set", "labels", "adversarial_pack"):
        if spec.get(key) != base_spec.get(key):
            out.append(f"ratchet: {key} changed ({base_spec.get(key)} -> {spec.get(key)}) on the same eval-set version")
    if sorted(spec.get("seeds") or []) != sorted(base_spec.get("seeds") or []):
        out.append(f"ratchet: seeds changed {base_spec.get('seeds')} -> {spec.get('seeds')}")
    bs, bb = spec.get("bootstrap") or {}, base_spec.get("bootstrap") or {}
    if bs.get("confidence", 0.95) > bb.get("confidence", 0.95):
        out.append(f"ratchet: bootstrap confidence {bb.get('confidence', 0.95)} -> {bs.get('confidence')} (wider CI)")
    if bs.get("method", "percentile") != bb.get("method", "percentile") or bs.get("rng", 2027) != bb.get("rng", 2027):
        out.append("ratchet: bootstrap method/rng changed (lets a PR shop for a favourable CI)")
    metrics = {m["id"]: m for m in spec.get("metrics") or []}
    for bm in base_spec.get("metrics") or []:
        m = metrics.get(bm["id"])
        if m is None:
            out.append(f"ratchet: metric {bm['id']} removed")
            continue
        if bm.get("blocking") and not m.get("blocking"):
            out.append(f"ratchet: metric {bm['id']} no longer blocking")
        out += [f"ratchet: metric {bm['id']} {x}" for x in _looser(m.get("threshold") or {}, bm.get("threshold") or {})]
    slices = {(s["name"], s["metric"]): s for s in spec.get("slices") or []}
    for bsl in base_spec.get("slices") or []:
        sid = f"slice:{bsl['name']}/{bsl['metric']}"
        sl = slices.get((bsl["name"], bsl["metric"]))
        if sl is None:
            out.append(f"ratchet: {sid} removed")
            continue
        if bsl.get("blocking") and not sl.get("blocking"):
            out.append(f"ratchet: {sid} no longer blocking")
        out += [f"ratchet: {sid} {x}" for x in _looser(sl, bsl)]
    return out


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for sl in spec.get("slices") or []:
        name, metric = sl["name"], sl["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        verdict, note, val = "ok", "", None
        if not a:
            # a slice with no graded rows cannot vouch for anything: treat as missing, never as a pass
            verdict = "missing"
        else:
            val = round(sum(a.values()) / len(a), 4)
            if "min" in sl and val < sl["min"]:
                verdict = "fail"
            if "max" in sl and val > sl["max"]:
                verdict = "fail"
            keys = sorted(set(a) & set(b))
            if sl.get("no_significant_drop") and keys:
                d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                   n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027),
                                                   confidence=bs.get("confidence", 0.95))
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"
        if verdict != "ok" and sl.get("blocking"):
            blocked.append(sid)
        th = {k: sl[k] for k in ("min", "max", "no_significant_drop") if k in sl}
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if sl.get("blocking") else "warn")
        lines.append(f"  {sid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}  (n_items={len(a)})")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
