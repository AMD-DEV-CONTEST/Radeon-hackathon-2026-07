# Servo action packages

Each managed action is delivered as `servo_actions/<action-id>/` with its own
`registry.json` and `action.py`. The runtime discovers these directories; there
is intentionally no shared action registry.

The `rdk-servo-action/v1` contract accepts only parameterless bridge-call sequences.
