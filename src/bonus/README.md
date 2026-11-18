# Bonus: port 3 grader sang Inspect AI và so khớp với pydantic-evals

Mọi lệnh chạy trong `src/`. Bonus **không** nằm trong CI: `inspect-ai` chỉ có trong `requirements-bonus.txt`, test bonus
(`tests/test_bonus_inspect.py`) không có marker `student` nên job `eval-gate`/`eval-gate-v2` không thu nó.

```bash
python -m pip install -r requirements-bonus.txt                     # inspect-ai==0.3.291
python -m bonus.inspect_port                                        # spec v2, 6 variant + 3 probe, exit 0 = khớp hết
python -m bonus.inspect_port --spec config/metric_spec.yaml --shapes swarm,fixed,seeded_regression
python -m pytest -q -o addopts= tests/test_bonus_inspect.py
```

## Cách port

| lab9 (pydantic-evals) | Inspect AI (`bonus/inspect_port.py`) |
|---|---|
| `Dataset` / `Case` = item@seed, `expected_output` = nhãn | `MemoryDataset` / `Sample(id="E-001@11")`, nhãn trong `metadata["label"]` (không phải `target`, để scorer không đọc nhầm chuỗi) |
| task `lab9.eval.make_task` chạy shape trên SQLite mới | `@solver run_agent` gọi **đúng** `make_task` đó, lưu Trial vào `state.store`; không gọi model |
| model: không có (MockLLM trong shape) | `model="mockllm/model"` có sẵn của Inspect, không bao giờ được gọi, không cần key |
| `ApprovalBypass` (True = vi phạm) | `@scorer no_approval_bypass` (INCORRECT = vi phạm) |
| `RefundAmountCorrect` | `@scorer refund_matches_label` |
| `ReplyMatchesLedger` (FM-08) | `@scorer reply_states_ledger_amount` |

Scorer được **viết lại từ định nghĩa** của grader (không import `lab9.graders`), nên khớp nghĩa là hai bản cài đặt độc lập
mã hóa cùng một luật. Cả hai harness chấm cùng một trial (cùng agent, cùng store mới, cùng nhãn), nên mọi khác biệt là lỗi grader.

## Kết quả (`python -m bonus.inspect_port`, 2026-11-18)

Ô = Inspect AI / pydantic-evals (`approval_bypass` = số lần vi phạm, còn lại = trung bình). 70 hoặc 140 trial / shape × 3 metric.

Spec v2 (28 item × 5 seed):

| Shape | approval_bypass | refund_amount_correct | reply_amount_matches_ledger | Khớp |
|---|---|---|---|---|
| swarm | 0 / 0 | 0.9786 / 0.9786 | 1.0 / 1.0 | 420/420 |
| fixed | 0 / 0 | 1.0 / 1.0 | 1.0 / 1.0 | 420/420 |
| honest_refactor | 0 / 0 | 1.0 / 1.0 | 1.0 / 1.0 | 420/420 |
| seeded_regression | 0 / 0 | 0.7857 / 0.7857 | 0.7143 / 0.7143 | 420/420 |
| slice_regression | 0 / 0 | 0.9357 / 0.9357 | 1.0 / 1.0 | 420/420 |
| flaky_regression | 0 / 0 | 0.9643 / 0.9643 | 1.0 / 1.0 | 420/420 |
| probe_sibling_refund | 55 / 55 | 0.6071 / 0.6071 | 1.0 / 1.0 | 420/420 |
| probe_misreport | 0 / 0 | 1.0 / 1.0 | 0.7857 / 0.7857 | 420/420 |
| probe_ignore_denied | 0 / 0 | 1.0 / 1.0 | 0.8571 / 0.8571 | 420/420 |
| **Tổng** | | | | **3780/3780** |

Spec v1 (14 item × 5 seed): swarm, fixed, seeded_regression → **630/630** khớp (seeded: refund 0.8571, reply 0.7857,
đúng bằng `reports/eval_seeded_regression.json`).

Ba shape `probe_*` (đăng ký trong bonus, không sửa `lab9/variants.py`) có để so khớp không bị "hiển nhiên": không variant
công khai nào làm `approval_bypass` bật, nên nếu chỉ so trên chúng thì 0 = 0 không chứng minh gì. `probe_sibling_refund`
(ghi refund dưới claim anh em) cho 55 vi phạm ở cả hai harness.

## Nhận xét so sánh hai harness

- **Giống:** cả hai chạy offline, cùng đơn vị là item@seed, grader code tất định → kết quả trùng từng dòng.
- **Inspect AI hơn:** log `.eval` có transcript từng sample (`inspect view --log-dir <dir>` để xem), `Score.explanation`
  hiện lý do ngay trong viewer; `epochs` có sẵn để lặp nhiều lần (tiện cho pass^k với model thật).
- **Inspect AI kém hơn ở bài này:** được thiết kế quanh một model được gọi ở solver; ở đây phải viết solver giả gọi agent
  Lab 8 và gắn `mockllm/model` cho có. Chậm hơn: ~2 phút cho 9 shape × 140 trial (gồm cả lần chạy pydantic-evals để so).
  Score là CORRECT/INCORRECT nên metric "an toàn" (True = xấu) phải đảo dấu khi map về lab9.
- **Lưu ý môi trường:** đừng đặt biến `INSPECT_TELEMETRY` (Inspect đọc nó như đường dẫn module hook, đặt `=0` làm `eval()` lỗi).
- Gate, bootstrap, slice và integrity vẫn chỉ ở `lab9.gate`; bonus không thay chúng, chỉ chứng minh grader cho cùng kết quả.
