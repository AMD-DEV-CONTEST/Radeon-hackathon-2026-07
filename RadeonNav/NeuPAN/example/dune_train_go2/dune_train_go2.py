import sys
import types

try:
    import tkinter  # noqa: F401
except ModuleNotFoundError:
    tkinter = types.ModuleType("tkinter")
    tkinter.Scale = object
    sys.modules["tkinter"] = tkinter

from neupan import neupan

planner = neupan.init_from_yaml("dune_train_go2.yaml")
planner.train_dune()
