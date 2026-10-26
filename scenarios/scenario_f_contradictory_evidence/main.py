import os

redis_enabled = os.environ.get("REDIS_ENABLED", "false").lower() == "true"
if redis_enabled:
    print("Using Redis cache")
else:
    print("Using in-memory cache")
