import sys

pytest_plugins = "pytest_homeassistant_custom_component"

if sys.platform == "win32":
    import pytest_socket

    # The Windows asyncio loop needs a local socketpair, which HA's test plugin would block.
    # Only the integration tests run on Windows; Home Assistant itself runs on Linux.
    pytest_socket.disable_socket = lambda *args, **kwargs: None
