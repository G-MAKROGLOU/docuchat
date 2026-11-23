"""HTTP status codes that the provider and source adapters try again."""

# Timeout, rate limit and server errors; other statuses are final.
RETRY_STATUSES = frozenset({408, 429, 500, 502, 503, 504})
