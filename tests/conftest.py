import pytest


@pytest.fixture(autouse=True)
def _simulated_signoff(monkeypatch):
    """Tests assert the simulated reviewers' decisions; the live app's human sign-off mode is tested explicitly."""
    monkeypatch.setenv("RECONAI_HUMAN_SIGNOFF", "off")
