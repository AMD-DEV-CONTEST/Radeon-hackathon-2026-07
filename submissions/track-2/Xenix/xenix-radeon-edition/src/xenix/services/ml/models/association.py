from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import joblib
import pandas as pd
from pydantic import BaseModel, Field

from ....exceptions import ValidationError
from ..contracts import (
    ApplySummary,
    ApplyTaskRequest,
    ApplyTaskResult,
    EvaluateTaskRequest,
    EvaluateTaskResult,
    FitTaskRequest,
    FitTaskResult,
    HyperparameterTuningTaskRequest,
    HyperparameterTuningTaskResult,
)
from ..dataset_loader import load_dataset
from ..types import (
    ColumnRoleKind,
    EvaluationKind,
    ModelFamily,
    ModelResultContract,
    ModelRoleDefinition,
    ModelRoleSchema,
    ModelServiceBase,
    ModelTaskKind,
)


class AssociationRulesParams(BaseModel):
    min_support: float = Field(default=0.02, gt=0.0, le=1.0)
    min_confidence: float = Field(default=0.2, gt=0.0, le=1.0)
    min_lift: float = Field(default=1.0, ge=0.0)
    min_length: int = Field(default=2, ge=2, le=10)
    top_k_per_input: int = Field(default=5, ge=1, le=50)


class AssociationRulesModelService(ModelServiceBase):
    evaluation_kind = EvaluationKind.SUMMARY
    model_family = ModelFamily.ASSOCIATION_RULES
    model_task_kind = ModelTaskKind.RULE_MINER
    requires_target = False
    supports_hyperparameter_tuning = False
    family = "Association rules"
    recommendation_tier = 40
    params_model = AssociationRulesParams
    backend_name: ClassVar[str]
    train_role_schema = ModelRoleSchema(
        roles=[
            ModelRoleDefinition(
                name="item",
                kind=ColumnRoleKind.MANY_COLUMNS,
                required=True,
                description="Basket item columns; each row is treated as one transaction.",
            )
        ],
        additional_roles=False,
    )
    apply_role_schema = train_role_schema
    result_contract = ModelResultContract(
        train_result_kinds=["model", "table"],
        apply_result_kinds=["table"],
        preview_kinds=["model", "table", "file"],
    )

    @classmethod
    def fit(cls, request: FitTaskRequest, task_dir: Path) -> FitTaskResult:
        dataframe = load_dataset(Path(request.dataset_source_path))
        item_columns = _role_columns(request.train_role_bindings, "item")
        transactions = _transactions_from_columns(dataframe, item_columns)
        params = cls.validate_params(request.manual_training.params)
        rules = cls._mine_rules(transactions, params)

        model_artifact_path = task_dir / "models" / f"{cls.key.replace('.', '_')}.joblib"
        export_artifact_path = task_dir / "output" / "association_rules.csv"
        model_artifact_path.parent.mkdir(parents=True, exist_ok=True)
        export_artifact_path.parent.mkdir(parents=True, exist_ok=True)
        rules.to_csv(export_artifact_path, index=False)
        joblib.dump(
            {
                "model_key": cls.key,
                "backend": cls.backend_name,
                "item_columns": item_columns,
                "params": params.model_dump(mode="json"),
                "rules": rules.to_dict(orient="records"),
            },
            model_artifact_path,
        )

        return FitTaskResult(
            task_id=request.task_id,
            evaluation_kind=request.evaluation_kind,
            evaluation_policy=request.evaluation_policy,
            model_key=cls.key,
            params=params.model_dump(mode="json"),
            model_artifact_path=str(model_artifact_path),
            export_artifact_path=str(export_artifact_path),
            result_summary={
                "result_count": int(len(rules.index)),
                "rule_count": int(len(rules.index)),
                "transaction_count": int(len(transactions)),
                "unique_item_count": int(len({item for basket in transactions for item in basket})),
                "backend": cls.backend_name,
            },
        )

    @classmethod
    def tune(cls, request: HyperparameterTuningTaskRequest, task_dir: Path) -> HyperparameterTuningTaskResult:
        raise ValidationError(f"Model '{cls.key}' does not support hyperparameter tuning.")

    @classmethod
    def evaluate(cls, request: EvaluateTaskRequest, task_dir: Path) -> EvaluateTaskResult:
        raise ValidationError(f"Model '{cls.key}' does not support evaluation.")

    @classmethod
    def apply(cls, request: ApplyTaskRequest, task_dir: Path) -> ApplyTaskResult:
        artifact = joblib.load(request.apply_model.trained_model_artifact_path)
        item_columns = [str(column) for column in artifact.get("item_columns") or request.feature_columns]
        rules = [dict(rule) for rule in artifact.get("rules") or []]
        params = AssociationRulesParams.model_validate(artifact.get("params") or {})
        result_rows: list[dict[str, Any]] = []

        for input_file in request.input_files:
            dataframe = load_dataset(Path(input_file.absolute_path))
            missing = [column for column in item_columns if column not in dataframe.columns]
            if missing:
                raise ValidationError(
                    f"Apply input '{input_file.file_name}' is missing required columns: {', '.join(missing)}."
                )
            transactions = _transactions_from_columns(dataframe, item_columns)
            for row_index, basket in enumerate(transactions, start=1):
                basket_set = set(basket)
                candidates = [
                    rule
                    for rule in rules
                    if set(_list_value(rule.get("antecedent_items"))).issubset(basket_set)
                ]
                candidates.sort(
                    key=lambda rule: (
                        -float(rule.get("confidence") or 0.0),
                        -float(rule.get("lift") or 0.0),
                        str(rule.get("consequent") or ""),
                    )
                )
                for rank, rule in enumerate(candidates[: params.top_k_per_input], start=1):
                    result_rows.append(
                        {
                            "source_file": input_file.file_name,
                            "input_row_number": row_index,
                            "input_items": ", ".join(basket),
                            "rank": rank,
                            "antecedent": str(rule.get("antecedent") or ""),
                            "recommended_items": str(rule.get("consequent") or ""),
                            "support": float(rule.get("support") or 0.0),
                            "confidence": float(rule.get("confidence") or 0.0),
                            "lift": float(rule.get("lift") or 0.0),
                        }
                    )

        output_dir = task_dir / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "association_recommendations.csv"
        pd.DataFrame(
            result_rows,
            columns=[
                "source_file",
                "input_row_number",
                "input_items",
                "rank",
                "antecedent",
                "recommended_items",
                "support",
                "confidence",
                "lift",
            ],
        ).to_csv(output_path, index=False)
        return ApplyTaskResult(
            task_id=request.task_id,
            trained_model_id=request.apply_model.trained_model_id,
            model_key=cls.key,
            output_file_path=str(output_path),
            summary=ApplySummary(
                row_count=len(result_rows),
                input_file_count=len(request.input_files),
                prediction_column_name="recommended_items",
            ),
        )

    @classmethod
    def _mine_rules(cls, transactions: list[list[str]], params: BaseModel) -> pd.DataFrame:
        raise NotImplementedError


class ApyoriAssociationRulesService(AssociationRulesModelService):
    key = "association.apriori_apyori"
    display_name = "Apriori Association Rules (apyori)"
    guidance = "Finds cross-sell product rules from row-based basket data using apyori."
    backend_name = "apyori"

    @classmethod
    def _mine_rules(cls, transactions: list[list[str]], params: BaseModel) -> pd.DataFrame:
        from apyori import apriori

        typed_params = AssociationRulesParams.model_validate(params)
        raw_rules = apriori(
            transactions,
            min_support=typed_params.min_support,
            min_confidence=typed_params.min_confidence,
            min_lift=typed_params.min_lift,
            min_length=typed_params.min_length,
        )
        rows: list[dict[str, Any]] = []
        for rule in raw_rules:
            for ordered_stat in rule.ordered_statistics:
                antecedent_items = sorted(str(item) for item in ordered_stat.items_base)
                consequent_items = sorted(str(item) for item in ordered_stat.items_add)
                if not antecedent_items or not consequent_items:
                    continue
                rows.append(
                    _rule_row(
                        antecedent_items=antecedent_items,
                        consequent_items=consequent_items,
                        support=float(rule.support),
                        confidence=float(ordered_stat.confidence),
                        lift=float(ordered_stat.lift),
                    )
                )
        return _rules_frame(rows)


class MlxtendAssociationRulesService(AssociationRulesModelService):
    key = "association.apriori_mlxtend"
    display_name = "Apriori Association Rules (mlxtend)"
    guidance = "Finds cross-sell product rules from row-based basket data using mlxtend."
    backend_name = "mlxtend"

    @classmethod
    def _mine_rules(cls, transactions: list[list[str]], params: BaseModel) -> pd.DataFrame:
        from mlxtend.frequent_patterns import apriori, association_rules
        from mlxtend.preprocessing import TransactionEncoder

        typed_params = AssociationRulesParams.model_validate(params)
        encoder = TransactionEncoder()
        encoded = encoder.fit(transactions).transform(transactions)
        one_hot = pd.DataFrame(encoded, columns=encoder.columns_)
        frequent_itemsets = apriori(
            one_hot,
            min_support=typed_params.min_support,
            use_colnames=True,
        )
        if frequent_itemsets.empty:
            return _rules_frame([])
        mined_rules = association_rules(
            frequent_itemsets,
            metric="confidence",
            min_threshold=typed_params.min_confidence,
        )
        mined_rules = mined_rules[mined_rules["lift"] >= typed_params.min_lift].copy()
        rows = [
            _rule_row(
                antecedent_items=sorted(str(item) for item in row.antecedents),
                consequent_items=sorted(str(item) for item in row.consequents),
                support=float(row.support),
                confidence=float(row.confidence),
                lift=float(row.lift),
            )
            for row in mined_rules.itertuples(index=False)
        ]
        return _rules_frame(rows)


def _role_columns(role_bindings: list[dict[str, Any]], role: str) -> list[str]:
    for binding in role_bindings:
        if binding.get("role") == role and isinstance(binding.get("columns"), list):
            return [str(column) for column in binding["columns"]]
    return []


def _transactions_from_columns(dataframe: pd.DataFrame, item_columns: list[str]) -> list[list[str]]:
    if not item_columns:
        raise ValidationError("Association rules require at least one item column.")
    missing = [column for column in item_columns if column not in dataframe.columns]
    if missing:
        raise ValidationError(f"Association item columns are missing: {', '.join(missing)}.")
    transactions: list[list[str]] = []
    for row in dataframe.loc[:, item_columns].itertuples(index=False, name=None):
        basket: list[str] = []
        seen: set[str] = set()
        for value in row:
            if pd.isna(value):
                continue
            item = str(value).strip()
            if not item or item in seen:
                continue
            basket.append(item)
            seen.add(item)
        if basket:
            transactions.append(basket)
    if not transactions:
        raise ValidationError("Association rules require at least one non-empty transaction.")
    return transactions


def _rule_row(
    *,
    antecedent_items: list[str],
    consequent_items: list[str],
    support: float,
    confidence: float,
    lift: float,
) -> dict[str, Any]:
    return {
        "antecedent_items": antecedent_items,
        "consequent_items": consequent_items,
        "antecedent": ", ".join(antecedent_items),
        "consequent": ", ".join(consequent_items),
        "support": support,
        "confidence": confidence,
        "lift": lift,
    }


def _rules_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        rows,
        columns=[
            "antecedent_items",
            "consequent_items",
            "antecedent",
            "consequent",
            "support",
            "confidence",
            "lift",
        ],
    )


def _list_value(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    return []
