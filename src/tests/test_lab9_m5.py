"""M5 (advanced): QuoteNotAltered step grader, slice gate edge cases, fm_map coverage."""
import copy

import pytest

pytestmark = pytest.mark.student


def _ctx(events):
    from pydantic_evals.evaluators import EvaluatorContext

    trial = {"snapshot": {"refund_vnd": 0, "refund_count": 0}, "unexpected_rows": 0, "blob": "", "events": events,
             "result": {}, "lab8_pass": True, "lab8_reason": None}
    return EvaluatorContext(name="t", inputs={}, metadata=None, expected_output={}, output=trial,
                            duration=0.0, _span_tree=None, attributes={}, metrics={})


QUOTE = {"kind": "quote", "payload": {"amount_vnd": 35000}}


@pytest.mark.parametrize("events,ok", [
    ([QUOTE], True),
    ([QUOTE, {"kind": "proposal", "payload": {"amount_vnd": 35000}}], True),     # restating the quote is fine
    ([QUOTE, {"kind": "proposal", "payload": {"amount_vnd": 30000}}], False),    # round_down
    ([QUOTE, {"kind": "proposal", "payload": {"amount_vnd": 0}}], False),        # pre_deducted to zero
    ([], True),
])
def test_quote_not_altered_advanced(events, ok):
    from lab9.graders import QuoteNotAltered

    assert QuoteNotAltered().evaluate(_ctx(events)).value is ok


def _report(rows):
    return {"manifest": {"eval_set_sha": "x", "items": 4, "seeds": [1, 2]}, "rows": rows,
            "metrics": {"pass_rate": 1.0}, "evaluator_failures": []}


ROWS = [{"item_id": f"E-{i:03d}", "seed": s, "pass_rate": True, "slices": ["money_movement"] if i < 2 else []}
        for i in range(4) for s in (1, 2)]


def test_slice_missing_blocks_advanced():
    from lab9 import gate

    spec = {"slices": [{"name": "adversarial", "metric": "pass_rate", "min": 0.9, "blocking": True}]}
    blocked, lines = gate.slice_check(_report(copy.deepcopy(ROWS)), _report(copy.deepcopy(ROWS)), spec)
    assert blocked == ["slice:adversarial/pass_rate"] and "MISSING" in lines[0]


def test_slice_significant_drop_blocks_above_floor_advanced():
    from lab9 import gate

    rows = copy.deepcopy(ROWS)
    rows[0]["pass_rate"] = False              # E-000 seed 1: slice mean 0.75, floor 0.5 still met
    spec = {"bootstrap": {"n_resamples": 200}, "slices": [
        {"name": "money_movement", "metric": "pass_rate", "min": 0.5, "no_significant_drop": True, "blocking": True}]}
    blocked, _ = gate.slice_check(_report(rows), _report(copy.deepcopy(ROWS)), spec)
    # 2 items, one drops by 0.5: CI hi is 0, not < 0, so the CI alone does not block -- the floor is what bites
    assert blocked == []


def test_fm_map_covers_every_pack_mechanism_advanced():
    import json
    from pathlib import Path

    import yaml

    mapping = yaml.safe_load(Path("config/fm_map.yaml").read_text(encoding="utf-8"))
    pack = json.loads(Path("data/eval/adversarial_v2.json").read_text(encoding="utf-8"))
    mechanisms = {m for c in pack["claims"] for m in c["mechanisms"]}
    assert all(str(mapping.get(m, "")).startswith("FM-") for m in mechanisms)


@pytest.mark.parametrize("args", [(5, 6, 1), (5, 2, 0), (3, 1, 4), (5, -1, 1), (0, 0, 1), (5.0, 2, 1), (5, True, 1), ("5", 2, 1)])
def test_pass_k_rejects_bad_counts_advanced(args):
    from lab9 import stats

    for fn in (stats.pass_at_k, stats.pass_hat_k):
        with pytest.raises(ValueError):
            fn(*args)


def test_pass_k_ordering_and_numpy_ints_advanced():
    import numpy as np

    from lab9 import stats

    for n, c in [(5, 0), (5, 3), (5, 5), (10, 7)]:
        for k in range(1, n + 1):
            assert stats.pass_hat_k(n, c, k) <= c / n + 1e-12 <= stats.pass_at_k(n, c, k) + 2e-12
    assert stats.pass_hat_k(np.int64(5), np.int64(4), 5) == 0.0
