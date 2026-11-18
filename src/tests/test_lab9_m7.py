"""M7 (expert): integrity_check against traps beyond lab9.traps (duplicates, green-run evaluator failures, edited
metrics, relabelled slices, ratchet dodges). Synthetic reports only, so this needs no file in reports/."""
import copy

import pytest

pytestmark = pytest.mark.student

SEEDS = [1, 2]
SPEC = {"eval_set_version": "v2", "seeds": SEEDS, "pass_k": [1, 2],
        "bootstrap": {"n_resamples": 200, "method": "percentile", "rng": 2027, "confidence": 0.95},
        "metrics": [{"id": "pass_rate", "kind": "capability", "blocking": True,
                     "threshold": {"min": 0.5, "no_significant_drop": True}},
                    {"id": "approval_bypass", "kind": "safety", "blocking": True, "threshold": {"max": 0}}],
        "slices": [{"name": "money_movement", "metric": "pass_rate", "min": 0.9, "blocking": True}]}


def _report(fail=()):
    from lab9.eval import aggregate

    rows = [{"item_id": f"E-{i:03d}", "seed": s, "slices": ["money_movement"] if i < 2 else [],
             "pass_rate": (i, s) not in fail, "approval_bypass": False, "cost": 1.0}
            for i in range(4) for s in SEEDS]
    return {"run_id": "t", "manifest": {"eval_set_sha": "x", "items": 4, "seeds": list(SEEDS)}, "rows": rows,
            "evaluator_failures": [], "metrics": aggregate(rows, ["pass_rate", "approval_bypass"], k_values=[1, 2])}


def _integrity(pr, base, spec=SPEC, base_spec=None):
    from lab9 import gate

    return gate.integrity_check(pr, base, spec, base_spec)


def test_clean_reports_are_trusted_advanced():
    assert _integrity(_report(), _report()) == []
    assert _integrity(_report(fail={(0, 1)}), _report(), SPEC, SPEC) == []


def test_duplicated_rows_advanced():
    pr = _report()
    pr["rows"] = pr["rows"] + copy.deepcopy(pr["rows"])
    pr["manifest"]["seeds"] = SEEDS * 2               # keep rows == items x seeds
    assert any("duplicated" in p for p in _integrity(pr, _report()))


def test_failing_row_swapped_for_a_passing_copy_advanced():
    pr = _report(fail={(0, 1)})
    pr["rows"][0] = copy.deepcopy(pr["rows"][1])     # same row count, one (item, seed) twice
    assert _integrity(pr, _report())


def test_evaluator_failures_on_green_run_advanced():
    pr = _report()
    pr["evaluator_failures"] = ["E-000@1:RefundAmountCorrect:KeyError"]
    assert any("evaluator failure" in p for p in _integrity(pr, _report()))


def test_hand_edited_metric_advanced():
    pr = _report(fail={(0, 1), (1, 1)})
    pr["metrics"]["pass_rate"] = 1.0
    assert any("rows give" in p for p in _integrity(pr, _report()))


@pytest.mark.parametrize("value", [None, "False", 0, float("nan")])
def test_non_bool_row_value_advanced(value):
    pr = _report()
    pr["rows"][0]["pass_rate"] = value
    assert _integrity(pr, _report())


def test_relabelled_out_of_slice_advanced():
    pr = _report(fail={(0, 1)})
    for r in pr["rows"]:
        if r["item_id"] == "E-000":
            r["slices"] = []
    assert any("slice tags" in p for p in _integrity(pr, _report()))


def test_inf_metric_advanced():
    pr = _report()
    pr["metrics"]["pass_hat_2"] = float("inf")
    assert _integrity(pr, _report())


@pytest.mark.parametrize("edit", [
    lambda s: s["slices"].clear(),
    lambda s: s["slices"][0].update(blocking=False),
    lambda s: s["slices"][0].update(min=0.5),
    lambda s: s["metrics"][0]["threshold"].pop("no_significant_drop"),
    lambda s: s["metrics"][1]["threshold"].update(max=1),
    lambda s: s["metrics"][0].update(blocking=False),
    lambda s: s["metrics"].pop(1),
    lambda s: s["bootstrap"].update(confidence=0.999),
    lambda s: s.update(seeds=[1]),
])
def test_ratchet_catches_loosening_advanced(edit):
    loose = copy.deepcopy(SPEC)
    edit(loose)
    assert any("ratchet" in p for p in _integrity(_report(), _report(), loose, SPEC))


def test_ratchet_allows_stricter_advanced():
    strict = copy.deepcopy(SPEC)
    strict["metrics"][0]["threshold"]["min"] = 0.9
    strict["slices"][0]["no_significant_drop"] = True
    strict["metrics"].append({"id": "new_metric", "kind": "capability", "blocking": True, "threshold": {"min": 1.0}})
    assert _integrity(_report(), _report(), strict, SPEC) == []


def test_version_bump_on_same_files_cannot_reset_ratchet_advanced():
    base_spec = dict(copy.deepcopy(SPEC), eval_set="data/eval/x.jsonl", labels="data/eval/y.json")
    bumped = dict(copy.deepcopy(base_spec), eval_set_version="v2.1", slices=[])
    assert _integrity(_report(), _report(), bumped, base_spec)
