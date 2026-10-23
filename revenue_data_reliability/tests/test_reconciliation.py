"""Unit tests for reconciliation math."""


def test_variance_formula():
    billings, gl = 110.0, 100.0
    variance = (billings - gl) / gl
    assert abs(variance - 0.10) < 1e-9


def test_severity_mapping():
    from backend.services.reconciliations import _severity

    assert _severity(0.025) == "critical"
    assert _severity(0.015) == "high"
    assert _severity(0.005) == "medium"


def test_status_boundary():
    tolerance = 0.05
    assert (abs(0.04) <= tolerance) is True
    assert (abs(0.06) <= tolerance) is False
