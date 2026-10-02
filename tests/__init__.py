"""Unit tests for AVD4Linux local device redirection (microphone / webcam pass-through)."""

import logging

# Keep expected warning/error paths from polluting the test output.
logging.getLogger("avd4linux").setLevel(logging.CRITICAL)
