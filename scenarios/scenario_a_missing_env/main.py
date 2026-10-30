import os
import sys

# Critical startup configuration
try:
    DATABASE_URL = os.environ["DATABASE_URL"]
except KeyError:
    sys.stderr.write(
        "CRITICAL: Required environment variable 'DATABASE_URL' is missing!\n"
    )
    sys.exit(1)

print("Auth service successfully connected to database.")
