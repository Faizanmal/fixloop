import os
import sys

print("Initializing payment processing worker...")
# Batch in-memory cache allocation triggers OOM when limit is 64M
data_buffer = [bytearray(1024 * 1024) for _ in range(80)]  # Allocates ~80MB
print("Processing batch completed.")
