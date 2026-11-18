"""Bonus: the Inspect AI port of 3 lab9 graders agrees with pydantic-evals row by row.
Not marked `student`, so the CI jobs (which run -m student) never collect it; skipped without inspect-ai
(pip install -r requirements-bonus.txt)."""
import pytest

pytest.importorskip("inspect_ai")


@pytest.fixture(autouse=True)
def _restore_shapes():
    """The port registers lab9 variants + probes into lab8's global SHAPES; put it back so the Lab 8
    contract tests that run later in the same process still see exactly the four shapes."""
    from lab8.shapes import SHAPES

    saved = dict(SHAPES)
    yield
    SHAPES.clear()
    SHAPES.update(saved)


@pytest.mark.parametrize("shape", ["seeded_regression", "probe_sibling_refund", "probe_misreport"])
def test_inspect_port_agrees_with_pydantic_evals(shape, tmp_path):
    from bonus import inspect_port

    inspect_port.register_probes()
    n, diffs, means = inspect_port.compare(shape, "config/metric_spec.yaml", str(tmp_path))
    assert n == 14 * 5 * 3 and diffs == []
    # the comparison is not vacuous: each probe makes its scorer fail somewhere
    if shape == "probe_sibling_refund":
        assert means["approval_bypass"][0] > 0
    if shape == "probe_misreport":
        assert means["reply_amount_matches_ledger"][0] < 1.0
    if shape == "seeded_regression":
        assert means["refund_amount_correct"][0] < 1.0
