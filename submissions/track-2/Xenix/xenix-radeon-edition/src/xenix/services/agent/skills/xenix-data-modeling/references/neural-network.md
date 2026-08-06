# Neural-network Comparison Reference

Use this file only when a simple neural network is being considered as a nonlinear comparison model. Do not make neural networks the default choice for business tabular data.

## When to consider

Consider a neural network only when:

- the task is classification or regression;
- sample size is large enough for stable training;
- features can be converted into numeric inputs;
- nonlinear relationships are plausible;
- an interpretable baseline has already been trained;
- the business values predictive lift enough to accept weaker interpretability.

Do not use when:

- sample size is small;
- target leakage or label quality is unresolved;
- the business requires simple explanations;
- baseline models already satisfy the decision need;
- the model tool cannot standardize numeric fields and encode categoricals.

## Tool workflow

1. Use `model.train` for an interpretable baseline.
2. Use `model.train` or `model.hyper_train` for a neural-network candidate only after the baseline.
3. Require the same metrics as the baseline.
4. Compare lift against baseline in business terms.
5. Request feature-importance or permutation-style explanation only if supported.
6. If neural network is not materially better, recommend the simpler model.

## Suggested Parameters

Read `references/model-presets.md` for MLP presets, and call `model.metadata` with the chosen neural-network `model_key` before passing parameters. Current Xenix MLP tools expose `hidden_layer_size` as one integer, not scikit-learn's `hidden_layer_sizes` tuple/list. Keep the search small:

```json
{
  "hidden_layer_size": [32, 64, 128],
  "alpha": [0.0001, 0.001, 0.01],
  "learning_rate_init": [0.001]
}
```

## Interpretation boundary

Use phrases like:

- “系统尝试了一种能够捕捉非线性关系的模型。”
- “相比基准模型，提升是否足以抵消解释性下降，需要结合业务场景判断。”
- “神经网络输出不能直接解释为因果关系。”
- “如果提升不明显，应优先采用更简单、可解释的模型。”

## Required risk notes

Mention:

- weaker interpretability;
- sensitivity to preprocessing and hyperparameters;
- overfitting risk;
- instability on small samples;
- need for periodic retraining;
- human review for high-risk decisions.
