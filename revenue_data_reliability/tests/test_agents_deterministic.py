"""Deterministic agent computation tests."""


def test_dq_build_summary():
    from backend.services.dq import build_summary

    results = [
        {"rule_id": "R1", "status": "pass", "summary_count": 0},
        {"rule_id": "R2", "status": "fail", "summary_count": 3},
    ]
    text = build_summary(results)
    assert "2 rules executed, 1 failed" in text
    assert "R2 (3)" in text


def test_dq_summary_with_recon():
    from backend.services.dq import build_summary

    results = [{"rule_id": "R1", "status": "pass", "summary_count": 0}]
    recon = {"rows": 5, "failed": 1, "exceptions_created": 1}
    text = build_summary(results, recon)
    assert "Reconciliation: 5 rows, 1 above tolerance, 1 exception(s) created." in text