"""Regression test from docs/trace_case.md: C-002 (T02), FM-03 ticket_trust.

The ticket says "trễ 5 ngày", order O-202 holds delay_days=2. The first wrong step in
seeded_regression C-002@11 is event 3 `model_override {"delay_days": 5}`; everything after it
(quote 20.000, ledger row) follows from that override. The check below must FAIL the buggy
variant and PASS `fixed` on the same claim@seed.
"""
import pytest

pytestmark = pytest.mark.student

CLAIM, SEED = "C-002", 11


def fm03_violations(trial: dict, label: dict) -> list[str]:
    """What a trajectory check for FM-03 reports on one trial (empty = clean)."""
    out = []
    overrides = [i for i, e in enumerate(trial["events"], 1) if e.get("kind") == "model_override"]
    if overrides:
        out.append(f"model_override at event {overrides[0]}")
    if trial["snapshot"].get("refund_vnd") != label["refund_vnd"]:
        out.append(f"ledger {trial['snapshot'].get('refund_vnd')} != label {label['refund_vnd']}")
    return out


@pytest.fixture(scope="module")
def investigate():
    from lab9.trace_case import investigate

    return investigate


def test_seeded_regression_c002_first_wrong_step_is_override(investigate):
    case = investigate("seeded_regression", CLAIM, SEED)
    trial, label = case["trial"], case["label"]
    kinds = [e.get("kind") for e in trial["events"]]
    # events 1-2 are correct (handoff, investigator reads delay_days=2 from the DB)
    assert kinds[:3] == ["handoff", "investigator", "model_override"]
    assert trial["events"][1]["payload"]["lookup_order"]["order"]["delay_days"] == 2
    assert trial["events"][2]["payload"] == {"delay_days": 5}
    assert fm03_violations(trial, label) == ["model_override at event 3", "ledger 20000 != label 0"]


def test_fixed_c002_keeps_db_fact(investigate):
    case = investigate("fixed", CLAIM, SEED)
    assert fm03_violations(case["trial"], case["label"]) == []
    assert case["trial"]["result"]["status"] == "denied"


def test_db_fact_kept_grader_agrees(investigate):
    from pydantic_evals.evaluators import EvaluatorContext

    from lab9.graders import DbFactKept

    def score(shape):
        case = investigate(shape, CLAIM, SEED)
        ctx = EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=case["label"],
                               output=case["trial"], duration=0.0, _span_tree=None, attributes={}, metrics={})
        return DbFactKept().evaluate(ctx).value

    assert score("seeded_regression") is False
    assert score("fixed") is True
