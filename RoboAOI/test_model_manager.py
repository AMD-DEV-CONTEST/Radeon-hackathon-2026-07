from roboaoi.model_manager import ModelManager

manager = ModelManager()

print("\nAvailable models:")
for name in manager.models:
    print(f"✓ {name}")
