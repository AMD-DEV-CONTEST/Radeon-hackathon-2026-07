"""Core abstractions: model base class, device management, pipeline factory.

This is the lowest layer — only depends on stdlib + torch + PIL.
No business logic here. If you find yourself reaching for a specific
model, you're in the wrong layer; go to `src.models/`.
"""
