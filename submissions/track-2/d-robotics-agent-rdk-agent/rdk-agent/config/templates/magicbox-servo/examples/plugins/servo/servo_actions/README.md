# Servo action packages

Each generated action owns one directory named after its kebab-case action ID:

```text
servo_actions/<action-id>/
├── registry.json
├── action.py
└── tests/
```

Create packages through `tools/servo_action.py new`; do not add a shared registry file here.
The `rdk-servo-action/v1` contract accepts only parameterless bridge-call sequences.
