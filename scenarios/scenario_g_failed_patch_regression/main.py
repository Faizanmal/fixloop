# App with configuration parameter
RATE_LIMIT_BURST = "unparsed_string"
if not isinstance(RATE_LIMIT_BURST, int):
    raise TypeError("RATE_LIMIT_BURST must be integer")

print("Service started successfully.")
