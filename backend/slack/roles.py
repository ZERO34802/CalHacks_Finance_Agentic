"""Who holds which AP role in Slack (`/reconai role <ap_lead|controller|cfo|cto>`). Owner: D.

The registry decides who gets which notification and button; every button still re-checks the role, the limit,
requester != approver and the release rule in code (backend/ap/actions.py, backend/ap/payments.py).
One Slack user holds one role (re-registering replaces it). A vendor's registered Slack user can't hold a role.
SIMULATED identity: in this demo people register themselves; in production the roles come from the HR / IdP.
"""
from __future__ import annotations

from typing import Iterable, Optional

from backend.store.base import Store
from contracts import Role, SlackRoleHolder

KIND = "slack_role"
NAMES = {"ap_lead": Role.approver, "ap": Role.approver, "approver": Role.approver, "controller": Role.controller,
         "cfo": Role.cfo, "cto": Role.cto}
TITLE = {Role.approver: "AP lead", Role.controller: "Controller", Role.cfo: "CFO", Role.cto: "CTO"}


def parse(name: str) -> Optional[Role]:
    return NAMES.get(name.strip().lower().replace("-", "_").replace(" ", "_"))


def register(store: Store, slack_user: str, name: str, email: str, role: Role) -> SlackRoleHolder:
    h = SlackRoleHolder(slack_user=slack_user, name=name, email=email.lower(), role=role)
    store.put_record(KIND, slack_user, h)
    return h


def holders(store: Store, roles: Optional[Iterable] = None) -> list[SlackRoleHolder]:
    want = {r.value if isinstance(r, Role) else str(r) for r in roles} if roles is not None else None
    out = [h for h in store.list_records(SlackRoleHolder, KIND) if want is None or h.role.value in want]
    return sorted(out, key=lambda h: (h.role.value, h.name))


def holder(store: Store, slack_user: str) -> Optional[SlackRoleHolder]:
    return store.get_record(SlackRoleHolder, KIND, slack_user)


def role_for_email(store: Store, email: str) -> Optional[str]:
    h = next((h for h in holders(store) if h.email == (email or "").lower()), None)
    return h.role.value if h else None
