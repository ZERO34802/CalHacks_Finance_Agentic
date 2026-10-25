import pytest


@pytest.fixture(autouse=True)
def _simulated_signoff(monkeypatch):
    """Tests assert the simulated reviewers' decisions; the live app's human sign-off mode is tested explicitly."""
    monkeypatch.setenv("RECONAI_HUMAN_SIGNOFF", "off")
    monkeypatch.setenv("RECONAI_CRS", "off")  # recorded CRS sandbox responses: tests never call the live sandbox


@pytest.fixture(autouse=True)
def _local_erp():
    """Never reach a real Odoo from tests (the repo .env may set ODOO_URL): the built-in ERP, reset after."""
    from backend import erp
    erp.set_erp(erp.LocalERP())
    yield
    erp.set_erp(None)
