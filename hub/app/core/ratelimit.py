"""Rate limiting configuration using slowapi."""

from slowapi import Limiter
from slowapi.util import get_remote_address

# Use client IP as the rate limit key
limiter = Limiter(key_func=get_remote_address)

# Rate limit constants
RATE_AUTH = "10/minute"
RATE_WRITE = "30/minute"
RATE_SEARCH = "60/minute"
RATE_SYNC = "10/minute"
RATE_DEFAULT = "120/minute"
