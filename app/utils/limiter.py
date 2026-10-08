"""
app/utils/limiter.py — Singleton slowapi rate-limiter instance.

Centralising the Limiter here means both main.py (which attaches it to
app.state) and the submission router (which uses it as a decorator) share
exactly the same object.  If they imported separate instances the state
would be out of sync and limits would never trigger.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

# key_func=get_remote_address extracts the client IP from the request.
# It respects the X-Forwarded-For header when present (set by proxies /
# load balancers), falling back to request.client.host.
limiter = Limiter(
    key_func=get_remote_address,
    # Global default applied to any route decorated with @limiter.limit()
    # that does not specify its own limit string.
    default_limits=["10/minute"],
)
