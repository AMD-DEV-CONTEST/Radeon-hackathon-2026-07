import sys
import types


# gctl imports tkinter.Scale even when NeuPAN is used without a GUI. Keep the
# tests runnable in the same headless environments used for robot deployment.
try:
    import tkinter  # noqa: F401
except ModuleNotFoundError:
    tkinter = types.ModuleType("tkinter")
    tkinter.Scale = object
    sys.modules["tkinter"] = tkinter
