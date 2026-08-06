"""behave environment hooks for the BDD suite.

The privacy scenario monkeypatches ``socket.socket`` with a guard that
rejects non-loopback connections. The guard is restored after every scenario
so a failure (or the live-model path in another scenario) can never leak the
patched socket into the rest of the run.
"""

import logging
import socket as socket_module


def before_all(context):
    # Keep Bunker's operational INFO logs out of the behave report; the
    # assertions already surface the observable behaviour.
    logging.getLogger("src.agent.permission_controller").setLevel(logging.WARNING)


def after_scenario(context, scenario):
    original = getattr(context, "_original_socket", None)
    if original is not None:
        socket_module.socket = original
        context._original_socket = None
