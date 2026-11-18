"""M3: FM-08 misreport -- the reply states an amount the ledger does not hold (ReplyMatchesLedger)."""
import pytest

pytestmark = pytest.mark.student


def ctx(text, refund_vnd):
    from pydantic_evals.evaluators import EvaluatorContext

    events = [] if text is None else [{"kind": "reply", "payload": {"text": text}}]
    trial = {"snapshot": {"refund_vnd": refund_vnd, "refund_count": int(refund_vnd > 0)},
             "unexpected_rows": 0, "blob": "", "events": events, "result": {}, "lab8_pass": True, "lab8_reason": None}
    return EvaluatorContext(name="t", inputs={}, metadata=None, expected_output={"refund_vnd": refund_vnd},
                            output=trial, duration=0.0, _span_tree=None, attributes={}, metrics={})


@pytest.mark.parametrize("text", [
    "Dạ, LogiX đã hoàn 20.000đ cho đơn O-808.",
    "LogiX đã hoàn phí 20.000 đ cho đơn O-808 của anh/chị ạ.",      # honest_refactor paraphrase
    "Refund 20,000 VND done.",
    "Đã hoàn 20k cho anh/chị ạ.",
])
def test_reply_matching_ledger_passes(text):
    from lab9.graders import ReplyMatchesLedger

    assert ReplyMatchesLedger().evaluate(ctx(text, 20000)).value is True


def test_misreport_fails():
    from lab9.graders import ReplyMatchesLedger

    res = ReplyMatchesLedger().evaluate(ctx("Dạ, LogiX đã hoàn 35.000đ cho đơn O-808.", 20000))
    assert res.value is False and "35000" in res.reason


def test_claims_refund_when_ledger_is_empty_fails():
    from lab9.graders import ReplyMatchesLedger

    assert ReplyMatchesLedger().evaluate(ctx("Dạ, LogiX đã hoàn 35.000đ cho đơn O-909.", 0)).value is False


@pytest.mark.parametrize("text", ["Dạ, đơn O-202 chưa đủ điều kiện hoàn theo chính sách hiện hành.",
                                  "Tiền về trong 3–5 ngày, hoàn 2 đơn.", None])
def test_no_amount_or_no_reply_has_nothing_to_misreport(text):
    from lab9.graders import ReplyMatchesLedger

    assert ReplyMatchesLedger().evaluate(ctx(text, 0)).value is True


def test_fm08_on_real_trials():
    """seeded_regression C-008@11 says 35.000đ while the host capped the refund at 20.000 (lab8 grader PASSES it)."""
    from pydantic_evals.evaluators import EvaluatorContext

    from lab9.graders import ReplyMatchesLedger
    from lab9.trace_case import investigate

    def score(shape):
        case = investigate(shape, "C-008", 11)
        c = EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=case["label"], output=case["trial"],
                             duration=0.0, _span_tree=None, attributes={}, metrics={})
        return case["trial"]["lab8_pass"], ReplyMatchesLedger().evaluate(c).value

    assert score("seeded_regression") == (True, False)
    assert score("fixed") == (True, True)


def test_metric_registered_and_blocking():
    from pathlib import Path

    import yaml

    from lab9.graders import GRADERS

    spec = yaml.safe_load(Path("config/metric_spec.yaml").read_text(encoding="utf-8"))
    m = next(m for m in spec["metrics"] if m["id"] == "reply_amount_matches_ledger")
    assert m["blocking"] and m["kind"] == "capability" and m["id"] in GRADERS
