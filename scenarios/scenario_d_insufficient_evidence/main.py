import os
import time

upstream = os.environ.get("UPSTREAM_HOST", "198.51.100.24")
print(f"Starting gateway-client on port 9000, connecting to {upstream}")

# Simulated external network failure
while True:
    time.sleep(1)
    print(f"Connection reset by peer from external gateway {upstream}")
