# Model Presets for `model.train`, `model.hyper_train`, and `model.apply`

Use this file before invoking model tools. Treat `model.metadata` as the source of truth for model keys, role schemas, accepted parameters, and accepted tuning grids.

## Non-negotiable Tool Rules

1. First call `model.metadata` with `model_family` to browse candidates.
2. After choosing one model, call `model.metadata` with that single `model_key` before passing unfamiliar params.
3. Use canonical `model_key` values returned by `model.metadata` whenever possible.
4. Pass only keys accepted by the model's `param_schema` or `param_grid_schema`.
5. Do not pass split policy, preprocessing policy, requested metrics, random seeds, or early-stopping flags unless `model.metadata` exposes those exact fields.
6. `model.train` payload shape:

```json
{
  "binding_id": "<binding_id>",
  "models": ["classification.logistic_regression"],
  "params_by_model": {
    "classification.logistic_regression": {"C": 1.0, "max_iter": 1000}
  }
}
```

7. `model.hyper_train` payload shape:

```json
{
  "binding_id": "<binding_id>",
  "param_grids_by_model": {
    "classification.logistic_regression": {"C": [0.1, 1.0, 10.0]}
  }
}
```

## Baseline Selection

Use these canonical keys as starting points after role binding is valid.

Classification:

- baseline: `classification.logistic_regression`
- nonlinear candidate: `classification.gradient_boosting`
- robust tree candidate: `classification.random_forest`
- neural-network comparison: `classification.mlp`

Regression:

- baseline: `regression.linear` or `regression.ridge`
- nonlinear candidate: `regression.gradient_boosting`
- robust tree candidate: `regression.random_forest`
- neural-network comparison: `regression.mlp`

## Classification Examples

Logistic regression baseline:

```json
{
  "models": ["classification.logistic_regression"],
  "params_by_model": {
    "classification.logistic_regression": {
      "C": 1.0,
      "max_iter": 1000
    }
  }
}
```

Small logistic regression tuning grid:

```json
{
  "param_grids_by_model": {
    "classification.logistic_regression": {
      "C": [0.1, 1.0, 10.0],
      "max_iter": [1000, 3000]
    }
  }
}
```

Gradient boosting classifier candidate:

```json
{
  "models": ["classification.gradient_boosting"],
  "params_by_model": {
    "classification.gradient_boosting": {
      "learning_rate": 0.05,
      "n_estimators": 200,
      "max_depth": 3
    }
  }
}
```

Small gradient boosting classifier tuning grid:

```json
{
  "param_grids_by_model": {
    "classification.gradient_boosting": {
      "learning_rate": [0.03, 0.05, 0.1],
      "n_estimators": [100, 300],
      "max_depth": [2, 3, 5]
    }
  }
}
```

Random forest classifier candidate:

```json
{
  "models": ["classification.random_forest"],
  "params_by_model": {
    "classification.random_forest": {
      "n_estimators": 300,
      "max_depth": 0,
      "max_features": "sqrt"
    }
  }
}
```

`max_depth: 0` means unbounded depth in current Xenix model adapters.

## Regression Examples

Ridge regression baseline:

```json
{
  "models": ["regression.ridge"],
  "params_by_model": {
    "regression.ridge": {
      "alpha": 1.0,
      "fit_intercept": true
    }
  }
}
```

Small ridge tuning grid:

```json
{
  "param_grids_by_model": {
    "regression.ridge": {
      "alpha": [0.1, 1.0, 10.0],
      "fit_intercept": [true, false]
    }
  }
}
```

Gradient boosting regressor candidate:

```json
{
  "models": ["regression.gradient_boosting"],
  "params_by_model": {
    "regression.gradient_boosting": {
      "learning_rate": 0.05,
      "n_estimators": 200,
      "max_depth": 3,
      "min_samples_leaf": 5
    }
  }
}
```

Random forest regressor candidate:

```json
{
  "models": ["regression.random_forest"],
  "params_by_model": {
    "regression.random_forest": {
      "n_estimators": 300,
      "max_depth": 0,
      "min_samples_leaf": 5,
      "max_features": "sqrt"
    }
  }
}
```

## Neural-Network Examples

Use only after an interpretable baseline exists.

Current Xenix MLP models expose `hidden_layer_size` as a single integer, not a list of layer sizes.

Classification:

```json
{
  "models": ["classification.mlp"],
  "params_by_model": {
    "classification.mlp": {
      "hidden_layer_size": 64,
      "activation": "relu",
      "alpha": 0.001,
      "learning_rate_init": 0.001,
      "max_iter": 500
    }
  }
}
```

Regression:

```json
{
  "models": ["regression.mlp"],
  "params_by_model": {
    "regression.mlp": {
      "hidden_layer_size": 64,
      "activation": "relu",
      "alpha": 0.001,
      "learning_rate_init": 0.001,
      "max_iter": 500
    }
  }
}
```

Small MLP tuning grid:

```json
{
  "param_grids_by_model": {
    "classification.mlp": {
      "hidden_layer_size": [32, 64, 128],
      "activation": ["relu", "tanh"],
      "alpha": [0.0001, 0.001],
      "learning_rate_init": [0.001]
    }
  }
}
```

Use `regression.mlp` instead of `classification.mlp` for regression.

## When to Stop Tuning

Stop tuning when:

- validation/test performance does not improve meaningfully;
- the tuned model becomes much less interpretable without business-value gain;
- runtime or complexity is disproportionate;
- model results are unstable across splits;
- data quality, label quality, or leakage risk dominates model choice.
