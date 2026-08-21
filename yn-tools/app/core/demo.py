"""Demo mode helpers (used when DEMO_MODE=true)."""

from datetime import datetime, timedelta
from types import SimpleNamespace


def _build_guest_user() -> SimpleNamespace:
    """Return an in-memory guest user shaped like app.users.models.User.

    Not persisted to DB — used only for templates and route dependencies
    when DEMO_MODE=true.
    """
    far_future = datetime.utcnow() + timedelta(days=365 * 10)
    return SimpleNamespace(
        id=0,
        google_id="demo-guest",
        email="guest@demo.ynfactory.online",
        name="ゲスト（デモ）",
        avatar_url=None,
        plan="all_tools",
        trial_ends_at=far_future,
        stripe_customer_id=None,
        stripe_subscription_id=None,
        is_active=True,
        is_admin=False,
        has_active_plan=True,
        has_full_access=True,
        is_in_trial=False,
        has_paid_plan_during_trial=False,
    )


GUEST_USER = _build_guest_user()
