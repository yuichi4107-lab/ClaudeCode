"""Middleware to check plan status and redirect expired users."""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse

# Paths that don't require an active plan
FREE_PATHS = {
    "/", "/auth", "/billing", "/static", "/dashboard",
    "/account", "/community",
}


class PlanGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path

        # Skip plan check for free paths
        if any(path.startswith(p) for p in FREE_PATHS):
            return await call_next(request)

        # Only check /tools/* paths
        if path.startswith("/tools/"):
            user_id = request.session.get("user_id")
            if not user_id:
                return RedirectResponse(url="/auth/login", status_code=303)

            # Plan check is done via the require_active_plan dependency
            # This middleware just ensures unauthenticated users are redirected

        return await call_next(request)
