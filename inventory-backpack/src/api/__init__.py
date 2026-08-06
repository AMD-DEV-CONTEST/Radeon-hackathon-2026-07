def __getattr__(name):
    if name == "create_app":
        from .server import create_app
        return create_app
    raise AttributeError(f"module {__name__} has no attribute {name}")