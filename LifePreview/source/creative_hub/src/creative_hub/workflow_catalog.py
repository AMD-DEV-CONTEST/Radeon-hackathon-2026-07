"""Versioned workflow catalog for the unified Creative Hub runtime.

Definitions in this module are declarative snapshots.  They never execute a
provider or write an artifact directly: capability nodes are resolved through
the frozen atomic registry, persisted as ``OperationRun`` facts, and then
materialized by the durable DAG scheduler.  Hub-owned control nodes use the
same durable queue but are dispatched to the quality/review/delivery services.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping, Sequence
from uuid import UUID, uuid5

from atomic_runtime import CapabilityRegistry
from shared_contracts import SchemaRevision
from sqlalchemy import select
from sqlalchemy.orm import Session

from .dag_execution import DagEdge, DagNode, DurableDagScheduler
from .dag_models import OperationDependencyStateRecord
from .db.canonical import canonical_json_digest
from .db.models import (
    OperationRunRecord,
    WorkflowDefinitionRecord,
    WorkflowDefinitionRevisionRecord,
    WorkflowRunRecord,
)
from .db.repositories import (
    OperationRepository,
    SelectionRepository,
    WorkflowRepository,
    WorkflowStored,
)


class WorkflowCatalogError(RuntimeError):
    """A catalog definition or materialization request is invalid."""


def _resolve_json_pointer(value: object, pointer: str) -> Any:
    current = value
    for raw_segment in pointer.removeprefix("/").split("/"):
        segment = raw_segment.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if segment not in current:
                raise WorkflowCatalogError(
                    f"workflow input binding is missing: {pointer}"
                )
            current = current[segment]
        elif isinstance(current, (list, tuple)):
            try:
                index = int(segment)
                current = current[index]
            except (ValueError, IndexError) as exc:
                raise WorkflowCatalogError(
                    f"workflow input binding is missing: {pointer}"
                ) from exc
        else:
            raise WorkflowCatalogError(
                f"workflow input binding is missing: {pointer}"
            )
    return current


_OPERATION_NAMESPACE = UUID("cab4a655-38cf-47f0-aef5-f968f8fbe109")
_NODE_NAMESPACE = UUID("90135ff9-11e9-4b90-ad79-8dd7b6fc93bb")
_POLICY_NAMESPACE = UUID("c09417c4-7c4b-431e-b7be-754e5dfca166")
_H3_SELECTION_HEAD_NAMESPACE = UUID("4e233ddb-0a37-4b40-823f-8f1229043b7e")
_H3_WORKFLOW_KEY = "factory.shidu-h3.v1"


class WorkflowNodeKind(StrEnum):
    CAPABILITY = "capability"
    QUALITY_GATE = "quality_gate"
    DELIVERY = "delivery"


@dataclass(frozen=True, slots=True)
class WorkflowNodeDefinition:
    key: str
    op_type: str
    kind: WorkflowNodeKind = WorkflowNodeKind.CAPABILITY
    depends_on: tuple[str, ...] = ()
    required_status: str = "SUCCEEDED"
    resource_pool: str | None = None
    priority_class: str = "interactive"
    estimated_cost_micros: int = 0
    structured_inputs: Mapping[str, Any] = field(default_factory=dict)
    parameter_snapshot: Mapping[str, Any] = field(default_factory=dict)
    structured_input_bindings: Mapping[str, str] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        if not self.key or len(self.key) > 200:
            raise WorkflowCatalogError("workflow node key is invalid")
        if not self.op_type or len(self.op_type) > 160:
            raise WorkflowCatalogError("workflow node operation is invalid")
        if len(self.depends_on) != len(set(self.depends_on)):
            raise WorkflowCatalogError("workflow node dependencies repeat")
        if self.required_status not in {"SUCCEEDED", "TERMINAL"}:
            raise WorkflowCatalogError(
                "workflow dependency status is invalid"
            )
        if self.estimated_cost_micros < 0:
            raise WorkflowCatalogError(
                "workflow estimated cost must be non-negative"
            )
        object.__setattr__(
            self,
            "structured_inputs",
            MappingProxyType(dict(self.structured_inputs)),
        )
        object.__setattr__(
            self,
            "parameter_snapshot",
            MappingProxyType(dict(self.parameter_snapshot)),
        )
        bindings = dict(self.structured_input_bindings)
        if any(
            not target
            or not isinstance(pointer, str)
            or not pointer.startswith("/")
            for target, pointer in bindings.items()
        ):
            raise WorkflowCatalogError(
                "structured input bindings must map names to JSON pointers"
            )
        object.__setattr__(
            self,
            "structured_input_bindings",
            MappingProxyType(bindings),
        )


@dataclass(frozen=True, slots=True)
class WorkflowDefinition:
    workflow_key: str
    name: str
    schema_revision: str
    nodes: tuple[WorkflowNodeDefinition, ...]

    def __post_init__(self) -> None:
        if not self.workflow_key or not self.name:
            raise WorkflowCatalogError(
                "workflow key and name must not be empty"
            )
        keys = tuple(node.key for node in self.nodes)
        if not keys or len(keys) != len(set(keys)):
            raise WorkflowCatalogError(
                "workflow node keys must be non-empty and unique"
            )
        available: set[str] = set()
        for node in self.nodes:
            missing = set(node.depends_on) - available
            if missing:
                raise WorkflowCatalogError(
                    f"workflow node {node.key!r} depends on later/unknown "
                    f"nodes: {sorted(missing)!r}"
                )
            available.add(node.key)

    def as_payload(self) -> dict[str, Any]:
        return {
            "workflow_key": self.workflow_key,
            "schema_revision": self.schema_revision,
            "nodes": [
                {
                    "key": node.key,
                    "op_type": node.op_type,
                    "kind": node.kind.value,
                    "depends_on": list(node.depends_on),
                    "required_status": node.required_status,
                    "resource_pool": node.resource_pool,
                    "priority_class": node.priority_class,
                    "estimated_cost_micros": node.estimated_cost_micros,
                    "structured_inputs": dict(node.structured_inputs),
                    "parameter_snapshot": dict(node.parameter_snapshot),
                    "structured_input_bindings": dict(
                        node.structured_input_bindings
                    ),
                }
                for node in self.nodes
            ],
        }


class WorkflowCatalog:
    """Immutable lookup of the workflow revisions shipped with this image."""

    def __init__(self, definitions: Sequence[WorkflowDefinition]) -> None:
        values = tuple(definitions)
        keys = tuple(item.workflow_key for item in values)
        if len(keys) != len(set(keys)):
            raise WorkflowCatalogError("workflow keys must be unique")
        self._definitions = MappingProxyType(
            {item.workflow_key: item for item in values}
        )

    @property
    def definitions(self) -> Mapping[str, WorkflowDefinition]:
        return self._definitions

    def get(self, workflow_key: str) -> WorkflowDefinition:
        try:
            return self._definitions[workflow_key]
        except KeyError as exc:
            raise WorkflowCatalogError(
                f"unknown workflow: {workflow_key}"
            ) from exc

    def require(self, workflow_key: str) -> WorkflowDefinition:
        """Explicit lookup spelling used by product-specific composition."""

        return self.get(workflow_key)


@dataclass(frozen=True, slots=True)
class MaterializedWorkflow:
    workflow: WorkflowStored
    run: WorkflowRunRecord
    operations: Mapping[str, OperationRunRecord]


class WorkflowMaterializer:
    """Persist a catalog snapshot and hand its nodes to the T4 scheduler."""

    def __init__(
        self,
        *,
        session: Session,
        scheduler: DurableDagScheduler,
        capability_registry: CapabilityRegistry,
    ) -> None:
        if not capability_registry.is_frozen:
            raise WorkflowCatalogError(
                "capability registry must be frozen before materialization"
            )
        self.session = session
        self.scheduler = scheduler
        self.capability_registry = capability_registry

    @staticmethod
    def _preflight_h3_selection_keys(
        *,
        definition: WorkflowDefinition,
        input_payload: Mapping[str, Any],
    ) -> Mapping[str, str]:
        if definition.workflow_key != _H3_WORKFLOW_KEY:
            return MappingProxyType({})
        selection_keys: dict[str, str] = {}
        seen_selection_keys: set[str] = set()
        root_structured_inputs = input_payload.get("structured_inputs")
        binding_source = (
            root_structured_inputs
            if isinstance(root_structured_inputs, Mapping)
            else input_payload
        )
        for node in definition.nodes:
            if node.op_type != "h3.attempt.select":
                continue
            structured_inputs = dict(node.structured_inputs)
            if not node.depends_on and isinstance(
                root_structured_inputs,
                Mapping,
            ):
                structured_inputs.update(root_structured_inputs)
            for target, pointer in node.structured_input_bindings.items():
                structured_inputs[target] = _resolve_json_pointer(
                    binding_source,
                    pointer,
                )
            ordinal = structured_inputs.get("sequence_ordinal")
            if type(ordinal) is not int or ordinal <= 0:
                raise WorkflowCatalogError(
                    "H3 selection sequence ordinal must be a positive integer"
                )
            expected_node_key = f"sequence.{ordinal:03d}.select"
            if node.key != expected_node_key:
                raise WorkflowCatalogError(
                    "H3 selection node key does not match its sequence ordinal"
                )
            selection_key = f"h3.sequence.{ordinal:03d}"
            if selection_key in seen_selection_keys:
                raise WorkflowCatalogError(
                    "H3 selection sequence ordinals must be unique"
                )
            seen_selection_keys.add(selection_key)
            selection_keys[node.key] = selection_key
        return MappingProxyType(selection_keys)

    def materialize(
        self,
        *,
        project_id: UUID,
        definition: WorkflowDefinition,
        command_idempotency_key: str,
        input_payload: Mapping[str, Any],
        policy_snapshot: Mapping[str, Any],
        created_by_actor: str,
        parent_workflow_run_id: UUID | None = None,
        source_repair_proposal_id: UUID | None = None,
    ) -> MaterializedWorkflow:
        h3_selection_keys = self._preflight_h3_selection_keys(
            definition=definition,
            input_payload=input_payload,
        )
        capabilities = self._capabilities_by_type()
        definition_payload = definition.as_payload()
        workflows = WorkflowRepository(self.session)
        stored_workflow = self._resolve_workflow_definition(
            repository=workflows,
            project_id=project_id,
            definition=definition,
            definition_payload=definition_payload,
            command_idempotency_key=command_idempotency_key,
            created_by_actor=created_by_actor,
        )
        run = workflows.create_workflow_run(
            project_id=project_id,
            workflow_definition_id=stored_workflow.definition.id,
            workflow_revision_id=stored_workflow.revision.id,
            command_idempotency_key=f"{command_idempotency_key}:run",
            input_payload=dict(input_payload),
            policy_snapshot=dict(policy_snapshot),
            parent_workflow_run_id=parent_workflow_run_id,
            source_repair_proposal_id=source_repair_proposal_id,
        ).value
        if h3_selection_keys:
            locked_run = self.session.scalar(
                select(WorkflowRunRecord)
                .where(
                    WorkflowRunRecord.id == run.id,
                    WorkflowRunRecord.project_id == project_id,
                )
                .with_for_update()
            )
            if (
                locked_run is None
                or locked_run.id != run.id
                or locked_run.project_id != project_id
            ):
                raise WorkflowCatalogError(
                    "H3 workflow run lock scope is inconsistent"
                )
            run = locked_run
        operations: dict[str, OperationRunRecord] = {}
        dag_nodes: list[DagNode] = []
        operation_repository = OperationRepository(self.session)
        selection_repository = SelectionRepository(self.session)
        for node in definition.nodes:
            capability = (
                capabilities.get(node.op_type)
                if node.kind is WorkflowNodeKind.CAPABILITY
                else None
            )
            if (
                node.kind is WorkflowNodeKind.CAPABILITY
                and capability is None
            ):
                raise WorkflowCatalogError(
                    f"capability is unavailable: {node.op_type}"
                )
            resource_pool = (
                node.resource_pool
                or (
                    capability.spec.resource_class.value
                    if capability is not None
                    else "cpu"
                )
            )
            if (
                capability is not None
                and resource_pool
                != capability.spec.resource_class.value
            ):
                raise WorkflowCatalogError(
                    "capability resource_pool override conflicts with "
                    f"registered resource class: {node.op_type}"
                )
            operation_run_id = uuid5(
                _OPERATION_NAMESPACE,
                f"{run.id}:{node.key}",
            )
            node_run_id = uuid5(
                _NODE_NAMESPACE,
                str(operation_run_id),
            )
            subject_domain = (
                "factory"
                if definition.workflow_key.startswith("factory.")
                else "creative"
            )
            structured_inputs = dict(node.structured_inputs)
            parameter_snapshot = dict(node.parameter_snapshot)
            repair_manifest = input_payload.get("repair_manifest")
            if isinstance(repair_manifest, Mapping):
                carried_values = repair_manifest.get(
                    "carried_forward_artifacts"
                )
                if not isinstance(carried_values, list):
                    raise WorkflowCatalogError(
                        "repair manifest carried artifacts must be a list"
                    )
                carried_by_node = {
                    item.get("node_key"): dict(item)
                    for item in carried_values
                    if isinstance(item, Mapping)
                    and isinstance(item.get("node_key"), str)
                }
                required_carried = structured_inputs.pop(
                    "carried_input_node_keys",
                    [],
                )
                if not isinstance(required_carried, list):
                    raise WorkflowCatalogError(
                        "repair carried input node keys must be a list"
                    )
                missing_carried = set(required_carried) - set(
                    carried_by_node
                )
                if missing_carried:
                    raise WorkflowCatalogError(
                        "repair manifest is missing carried artifacts: "
                        f"{sorted(missing_carried)!r}"
                    )
                structured_inputs["repair_lineage"] = {
                    "parent_workflow_run_id": repair_manifest.get(
                        "parent_workflow_run_id"
                    ),
                    "source_repair_proposal_id": repair_manifest.get(
                        "source_repair_proposal_id"
                    ),
                    "manifest_digest": canonical_json_digest(
                        dict(repair_manifest)
                    ),
                }
                if required_carried:
                    structured_inputs["carried_artifacts"] = [
                        carried_by_node[key] for key in required_carried
                    ]
            if not node.depends_on:
                root_structured_inputs = input_payload.get(
                    "structured_inputs"
                )
                if isinstance(root_structured_inputs, Mapping):
                    structured_inputs.update(root_structured_inputs)
                root_parameter_snapshot = input_payload.get(
                    "parameter_snapshot"
                )
                if isinstance(root_parameter_snapshot, Mapping):
                    parameter_snapshot.update(root_parameter_snapshot)
            binding_source = input_payload.get("structured_inputs")
            if not isinstance(binding_source, Mapping):
                binding_source = input_payload
            for target, pointer in node.structured_input_bindings.items():
                structured_inputs[target] = _resolve_json_pointer(
                    binding_source,
                    pointer,
                )
            selection_key = h3_selection_keys.get(node.key)
            request_payload = {
                "workflow_node_kind": node.kind.value,
                "op_type": node.op_type,
                "structured_inputs": structured_inputs,
                "parameter_snapshot": parameter_snapshot,
                "input_node_keys": list(node.depends_on),
                "operation_request_binding": {
                    "binding_schema_version": (
                        "operation-request-binding.v1"
                    ),
                    "node_run_id": str(node_run_id),
                    "policy_snapshot_id": str(
                        uuid5(
                            _POLICY_NAMESPACE,
                            f"{run.id}:{run.policy_digest}",
                        )
                    ),
                    "subject_ref": {
                        "domain": subject_domain,
                        "entity_type": "workflow",
                        "entity_id": str(run.id),
                    },
                    "root_workflow_inputs": not node.depends_on,
                    "upstream_node_keys": list(node.depends_on),
                },
            }
            if capability is not None:
                request_payload.update(
                    {
                        "op_version": capability.spec.op_version.model_dump(
                            mode="json"
                        ),
                        "operation_spec_digest": (
                            capability.spec.spec_digest
                        ),
                        "implementation_digest": (
                            capability.implementation_manifest
                            .implementation_digest
                        ),
                        "input_schema_version": (
                            capability.spec.input_schema_version.model_dump(
                                mode="json"
                            )
                        ),
                        "output_schema_version": (
                            capability.spec.output_schema_version.model_dump(
                                mode="json"
                            )
                        ),
                    }
                )
                op_version = _revision_text(capability.spec.op_version)
            else:
                op_version = "1.0"
            operation = operation_repository.create_operation_run(
                project_id=project_id,
                workflow_run_id=run.id,
                node_key=node.key,
                op_type=node.op_type,
                op_version=op_version,
                command_idempotency_key=(
                    f"{command_idempotency_key}:operation:{node.key}"
                ),
                request_payload=request_payload,
                operation_run_id=operation_run_id,
            ).value
            if selection_key is not None:
                selection_head_id = uuid5(
                    _H3_SELECTION_HEAD_NAMESPACE,
                    f"{run.id}:{selection_key}",
                )
                selection_head = selection_repository.create_head(
                    project_id=project_id,
                    workflow_run_id=run.id,
                    selection_key=selection_key,
                    selection_head_id=selection_head_id,
                ).value
                if selection_head.id != selection_head_id:
                    raise WorkflowCatalogError(
                        "H3 selection head identity is inconsistent"
                    )
            operations[node.key] = operation
            dag_nodes.append(
                DagNode(
                    operation_run_id=operation.id,
                    resource_pool=resource_pool,
                    priority_class=node.priority_class,
                    estimated_cost_micros=node.estimated_cost_micros,
                )
            )
        dag_edges = tuple(
            DagEdge(
                upstream_operation_run_id=operations[parent].id,
                downstream_operation_run_id=operations[node.key].id,
                required_status=node.required_status,
            )
            for node in definition.nodes
            for parent in node.depends_on
        )
        projected = set(
            self.session.scalars(
                select(
                    OperationDependencyStateRecord.operation_run_id
                ).where(
                    OperationDependencyStateRecord.operation_run_id.in_(
                        [item.operation_run_id for item in dag_nodes]
                    )
                )
            )
        )
        expected = {item.operation_run_id for item in dag_nodes}
        if not projected:
            self.scheduler.materialize(
                workflow_run_id=run.id,
                nodes=tuple(dag_nodes),
                edges=dag_edges,
            )
        elif projected != expected:
            raise WorkflowCatalogError(
                "workflow materialization is only partially projected"
            )
        return MaterializedWorkflow(
            workflow=stored_workflow,
            run=run,
            operations=MappingProxyType(operations),
        )

    def _resolve_workflow_definition(
        self,
        *,
        repository: WorkflowRepository,
        project_id: UUID,
        definition: WorkflowDefinition,
        definition_payload: dict[str, Any],
        command_idempotency_key: str,
        created_by_actor: str,
    ) -> WorkflowStored:
        workflow = self.session.scalar(
            select(WorkflowDefinitionRecord)
            .where(
                WorkflowDefinitionRecord.project_id == project_id,
                WorkflowDefinitionRecord.workflow_key
                == definition.workflow_key,
            )
            .with_for_update()
        )
        if workflow is not None:
            if workflow.name != definition.name:
                raise WorkflowCatalogError(
                    "workflow catalog name conflicts with durable definition"
                )
            revision = self.session.scalar(
                select(WorkflowDefinitionRevisionRecord).where(
                    WorkflowDefinitionRevisionRecord.project_id
                    == project_id,
                    WorkflowDefinitionRevisionRecord.workflow_definition_id
                    == workflow.id,
                    WorkflowDefinitionRevisionRecord.revision
                    == workflow.current_revision,
                )
            )
            if revision is None:
                raise WorkflowCatalogError(
                    "current workflow definition revision is unavailable"
                )
            expected_digest = canonical_json_digest(
                {
                    "definition": definition_payload,
                    "schema_revision": definition.schema_revision,
                }
            )
            if (
                revision.definition_digest == expected_digest
                and revision.schema_revision
                == definition.schema_revision
            ):
                return WorkflowStored(workflow, revision, False)
        return repository.create_workflow_definition(
            project_id=project_id,
            workflow_key=definition.workflow_key,
            name=definition.name,
            definition=definition_payload,
            schema_revision=definition.schema_revision,
            command_idempotency_key=(
                f"{command_idempotency_key}:definition"
            ),
            created_by_actor=created_by_actor,
        )

    def append_same_stage_repair(
        self,
        *,
        materialized: MaterializedWorkflow,
        parent_node_key: str,
        repair_node: WorkflowNodeDefinition,
        gate_node: WorkflowNodeDefinition,
        command_idempotency_key: str,
        expected_selection_version: int,
    ) -> Mapping[str, OperationRunRecord]:
        """Append one immutable generation + gate pair for a QC repair."""

        if expected_selection_version < 0:
            raise WorkflowCatalogError(
                "repair selection version must be non-negative"
            )
        if (
            repair_node.kind is not WorkflowNodeKind.CAPABILITY
            or gate_node.kind is not WorkflowNodeKind.QUALITY_GATE
        ):
            raise WorkflowCatalogError(
                "repair expansion requires capability then quality gate"
            )
        if repair_node.depends_on != (parent_node_key,):
            raise WorkflowCatalogError(
                "repair must derive from the rejected candidate node"
            )
        if gate_node.depends_on != (repair_node.key,):
            raise WorkflowCatalogError(
                "repair gate must bind the derived candidate"
            )
        if parent_node_key not in materialized.operations:
            raise WorkflowCatalogError("repair parent node is unavailable")
        capabilities = self._capabilities_by_type()
        registration = capabilities.get(repair_node.op_type)
        if registration is None:
            raise WorkflowCatalogError(
                f"capability is unavailable: {repair_node.op_type}"
            )
        repository = OperationRepository(self.session)
        parent = materialized.operations[parent_node_key]
        created: dict[str, OperationRunRecord] = {}
        for node, parent_operation_id in (
            (repair_node, parent.id),
            (gate_node, None),
        ):
            capability = (
                registration
                if node.kind is WorkflowNodeKind.CAPABILITY
                else None
            )
            operation_run_id = uuid5(
                _OPERATION_NAMESPACE,
                (
                    f"{materialized.run.id}:"
                    f"{command_idempotency_key}:{node.key}"
                ),
            )
            request_payload: dict[str, Any] = {
                "workflow_node_kind": node.kind.value,
                "op_type": node.op_type,
                "structured_inputs": dict(node.structured_inputs),
                "parameter_snapshot": dict(node.parameter_snapshot),
                "input_node_keys": list(node.depends_on),
                "expected_selection_version": (
                    expected_selection_version
                ),
                "operation_request_binding": {
                    "binding_schema_version": (
                        "operation-request-binding.v1"
                    ),
                    "node_run_id": str(
                        uuid5(_NODE_NAMESPACE, str(operation_run_id))
                    ),
                    "policy_snapshot_id": str(
                        uuid5(
                            _POLICY_NAMESPACE,
                            (
                                f"{materialized.run.id}:"
                                f"{materialized.run.policy_digest}"
                            ),
                        )
                    ),
                    "subject_ref": {
                        "domain": "factory",
                        "entity_type": "workflow",
                        "entity_id": str(materialized.run.id),
                    },
                    "root_workflow_inputs": False,
                    "upstream_node_keys": list(node.depends_on),
                },
            }
            if capability is not None:
                request_payload.update(
                    {
                        "op_version": capability.spec.op_version.model_dump(
                            mode="json"
                        ),
                        "operation_spec_digest": capability.spec.spec_digest,
                        "implementation_digest": (
                            capability.implementation_manifest
                            .implementation_digest
                        ),
                        "input_schema_version": (
                            capability.spec.input_schema_version.model_dump(
                                mode="json"
                            )
                        ),
                        "output_schema_version": (
                            capability.spec.output_schema_version.model_dump(
                                mode="json"
                            )
                        ),
                    }
                )
            created[node.key] = repository.create_operation_run(
                project_id=materialized.run.project_id,
                workflow_run_id=materialized.run.id,
                node_key=node.key,
                op_type=node.op_type,
                op_version=(
                    _revision_text(capability.spec.op_version)
                    if capability is not None
                    else "1.0"
                ),
                command_idempotency_key=(
                    f"{command_idempotency_key}:operation:{node.key}"
                ),
                request_payload=request_payload,
                parent_operation_run_id=parent_operation_id,
                operation_run_id=operation_run_id,
            ).value
        nodes = (
            DagNode(
                operation_run_id=created[repair_node.key].id,
                resource_pool=(
                    repair_node.resource_pool
                    or registration.spec.resource_class.value
                ),
                priority_class=repair_node.priority_class,
                estimated_cost_micros=repair_node.estimated_cost_micros,
            ),
            DagNode(
                operation_run_id=created[gate_node.key].id,
                resource_pool=gate_node.resource_pool or "cpu",
                priority_class=gate_node.priority_class,
                estimated_cost_micros=gate_node.estimated_cost_micros,
            ),
        )
        expected = {item.operation_run_id for item in nodes}
        projected = set(
            self.session.scalars(
                select(
                    OperationDependencyStateRecord.operation_run_id
                ).where(
                    OperationDependencyStateRecord.operation_run_id.in_(
                        expected
                    )
                )
            )
        )
        if not projected:
            self.scheduler.extend(
                workflow_run_id=materialized.run.id,
                nodes=nodes,
                edges=(
                    DagEdge(
                        upstream_operation_run_id=parent.id,
                        downstream_operation_run_id=(
                            created[repair_node.key].id
                        ),
                    ),
                    DagEdge(
                        upstream_operation_run_id=(
                            created[repair_node.key].id
                        ),
                        downstream_operation_run_id=created[gate_node.key].id,
                    ),
                ),
            )
        elif projected != expected:
            raise WorkflowCatalogError(
                "repair materialization is only partially projected"
            )
        return MappingProxyType(created)

    def _capabilities_by_type(self):
        by_type: dict[str, Any] = {}
        for registration in self.capability_registry.registrations.values():
            existing = by_type.get(registration.spec.op_type)
            if existing is not None:
                raise WorkflowCatalogError(
                    "catalog materialization requires exactly one installed "
                    f"revision per operation type: {registration.spec.op_type}"
                )
            by_type[registration.spec.op_type] = registration
        return by_type


def _revision_text(value: SchemaRevision) -> str:
    return f"{value.major}.{value.minor}"


def shidu_trial_workflow_definition() -> WorkflowDefinition:
    """Return the frozen six-shot, six-cue Shidu production DAG.

    The graph records only immutable identities and artifact-producing
    operations.  It intentionally contains no mouth-animation operation,
    parameter, or recovery route.
    """

    nodes: list[WorkflowNodeDefinition] = [
        WorkflowNodeDefinition(
            "trial-plan",
            "assembly.plan",
            structured_inputs={
                "schema_version": "factory.shidu-trial-input.v1",
                "shot_count": 6,
                "cue_count": 6,
            },
        )
    ]
    for index in range(1, 7):
        suffix = f"{index:03d}"
        nodes.extend(
            (
                WorkflowNodeDefinition(
                    f"shot-plan.{suffix}",
                    "episode.shot.plan",
                    depends_on=("trial-plan",),
                    structured_inputs={"ordinal": index},
                ),
                WorkflowNodeDefinition(
                    f"keyframe.{suffix}",
                    "keyframe.generate",
                    depends_on=(f"shot-plan.{suffix}",),
                    structured_inputs={
                        "ordinal": index,
                        "frame_role": "first_frame",
                    },
                    parameter_snapshot={"seed": 6100 + index},
                ),
                WorkflowNodeDefinition(
                    f"generation.{suffix}",
                    "generation.bind",
                    depends_on=(
                        f"shot-plan.{suffix}",
                        f"keyframe.{suffix}",
                    ),
                    structured_inputs={
                        "ordinal": index,
                        "contract": "shidu-direct-generation.v1",
                    },
                ),
                WorkflowNodeDefinition(
                    f"prompt.{suffix}",
                    "prompt.compile",
                    depends_on=(
                        f"shot-plan.{suffix}",
                        f"generation.{suffix}",
                    ),
                    structured_inputs={
                        "ordinal": index,
                        "contract": "shidu-direct-generation.v1",
                    },
                ),
                WorkflowNodeDefinition(
                    f"clip.{suffix}",
                    "video.generate",
                    depends_on=(
                        f"shot-plan.{suffix}",
                        f"keyframe.{suffix}",
                        f"generation.{suffix}",
                        f"prompt.{suffix}",
                    ),
                    structured_inputs={
                        "ordinal": index,
                        "mode": "i2v",
                    },
                    parameter_snapshot={"seed": 6200 + index},
                    estimated_cost_micros=500,
                ),
                WorkflowNodeDefinition(
                    f"clip-gate.{suffix}",
                    "qc.gate.clip",
                    kind=WorkflowNodeKind.QUALITY_GATE,
                    depends_on=(f"clip.{suffix}",),
                    structured_inputs={
                        "ordinal": index,
                        "release_scope": "current_script_revision",
                    },
                ),
                WorkflowNodeDefinition(
                    f"speech.{suffix}",
                    "speech.synthesize",
                    depends_on=("trial-plan",),
                    structured_inputs={
                        "ordinal": index,
                        "provider": "qwen3-tts-custom-voice-mcp",
                        "artifact_required": True,
                    },
                ),
                WorkflowNodeDefinition(
                    f"subtitle.{suffix}",
                    "subtitle.generate",
                    depends_on=(f"speech.{suffix}",),
                    structured_inputs={
                        "ordinal": index,
                        "timing_authority": "measured_tts_take",
                    },
                ),
            )
        )
    speech_keys = tuple(f"speech.{index:03d}" for index in range(1, 7))
    subtitle_keys = tuple(
        f"subtitle.{index:03d}" for index in range(1, 7)
    )
    clip_gate_keys = tuple(
        f"clip-gate.{index:03d}" for index in range(1, 7)
    )
    nodes.extend(
        (
            WorkflowNodeDefinition(
                "audio-mix",
                "audio.mix",
                depends_on=(*speech_keys, *subtitle_keys),
                structured_inputs={
                    "cue_count": 6,
                    "timeline_authority": "measured_audio_alignment_revision",
                    "track_authority": (
                        "accepted_artifact_or_silence_policy_revision"
                    ),
                    "playback_rate_policy": "unchanged",
                },
            ),
            WorkflowNodeDefinition(
                "assemble",
                "final.assemble",
                depends_on=(
                    "trial-plan",
                    "audio-mix",
                    *clip_gate_keys,
                    *subtitle_keys,
                ),
                structured_inputs={
                    "shot_count": 6,
                    "cue_count": 6,
                    "join_barrier": "all_current_revision_artifacts",
                },
            ),
            WorkflowNodeDefinition(
                "final-gate",
                "qc.gate.final",
                kind=WorkflowNodeKind.QUALITY_GATE,
                depends_on=("assemble",),
                structured_inputs={"stage": "final", "review_phase": "machine"},
            ),
            WorkflowNodeDefinition(
                "delivery",
                "delivery.publish",
                kind=WorkflowNodeKind.DELIVERY,
                depends_on=("final-gate",),
                structured_inputs={
                    "requires_machine_qc": True,
                    "requires_human_approval": False,
                    "artifact_lineage_required": True,
                },
            ),
        )
    )
    return WorkflowDefinition(
        workflow_key="factory.shidu-trial.v1",
        name="临界一刻六镜试读真实生产链",
        schema_revision="workflow.v1",
        nodes=tuple(nodes),
    )


def h3_shidu_workflow_definition(sequence_count: int) -> WorkflowDefinition:
    """Return the serial native-audio H3 production DAG."""

    if type(sequence_count) is not int or not 1 <= sequence_count <= 12:
        raise WorkflowCatalogError(
            "H3 workflow sequence_count must be an integer from 1 to 12"
        )
    nodes: list[WorkflowNodeDefinition] = [
        WorkflowNodeDefinition(
            "project-ir",
            "project_ir.generate",
        ),
        WorkflowNodeDefinition(
            "reference-generate",
            "character_reference.generate",
            depends_on=("project-ir",),
            resource_pool="local_gpu",
        ),
        WorkflowNodeDefinition(
            "reference-qc",
            "character_reference.qc",
            depends_on=("reference-generate",),
        ),
        WorkflowNodeDefinition(
            "reference-freeze",
            "character_reference.freeze",
            depends_on=("reference-generate", "reference-qc"),
        ),
        WorkflowNodeDefinition(
            "episode-ir",
            "episode_ir.generate",
            depends_on=("project-ir", "reference-freeze"),
        ),
    ]
    selected_sequences: list[str] = []
    for ordinal in range(1, sequence_count + 1):
        suffix = f"{ordinal:03d}"
        execute_key = f"sequence.{suffix}.execute"
        select_key = f"sequence.{suffix}.select"
        execute_dependencies = [
            "episode-ir",
            "reference-generate",
            "reference-freeze",
        ]
        if selected_sequences:
            execute_dependencies.append(selected_sequences[-1])
        nodes.extend(
            (
                WorkflowNodeDefinition(
                    execute_key,
                    "h3.sequence.execute",
                    depends_on=tuple(execute_dependencies),
                    resource_pool="local_gpu",
                    structured_inputs={
                        "sequence_ordinal": ordinal,
                        "mode": "ref2va",
                        "model_family": "minimax-h3",
                        "model_revision": "h3-amd-local-v1",
                        "max_generation_attempts": 2,
                        "repair_budget": 1,
                        "native_audio": True,
                        "subtitles": False,
                    },
                ),
                WorkflowNodeDefinition(
                    select_key,
                    "h3.attempt.select",
                    depends_on=(execute_key,),
                    structured_inputs={
                        "sequence_ordinal": ordinal,
                        "candidate_attempt_ordinals": [0, 1],
                        "selection_policy": (
                            "clean-first-lexicographic-qc-initial-tie.v1"
                        ),
                        "deliver_best_with_qc_exception": True,
                    },
                ),
            )
        )
        selected_sequences.append(select_key)
    nodes.extend(
        (
            WorkflowNodeDefinition(
                "assemble",
                "final.assemble",
                depends_on=tuple(selected_sequences),
                structured_inputs={
                    "video_codec": "h264",
                    "audio_codec": "aac",
                    "audio_source": "h3_native",
                    "subtitles": False,
                },
            ),
            WorkflowNodeDefinition(
                "final-gate",
                "qc.gate.final",
                kind=WorkflowNodeKind.QUALITY_GATE,
                depends_on=("assemble",),
            ),
            WorkflowNodeDefinition(
                "delivery",
                "delivery.publish",
                kind=WorkflowNodeKind.DELIVERY,
                depends_on=("final-gate",),
            ),
        )
    )
    return WorkflowDefinition(
        workflow_key=_H3_WORKFLOW_KEY,
        name="拾读 H3 原生音画串行生产链",
        schema_revision="workflow.v1",
        nodes=tuple(nodes),
    )


def default_workflow_catalog() -> WorkflowCatalog:
    """Return the complete R3 catalog in dependency order."""

    video_learning = WorkflowDefinition(
        workflow_key="video.learning.v1",
        name="视频学习与证据归纳",
        schema_revision="workflow.v1",
        nodes=(
            WorkflowNodeDefinition("source", "source.resolve"),
            WorkflowNodeDefinition(
                "probe", "media.probe", depends_on=("source",)
            ),
            WorkflowNodeDefinition(
                "audio", "audio.extract", depends_on=("source",)
            ),
            WorkflowNodeDefinition(
                "scenes", "scene.detect", depends_on=("probe",)
            ),
            WorkflowNodeDefinition(
                "frame-plan", "frame.plan", depends_on=("scenes",)
            ),
            WorkflowNodeDefinition(
                "frames", "frame.extract", depends_on=("frame-plan",)
            ),
            WorkflowNodeDefinition(
                "transcript", "speech.transcribe", depends_on=("audio",)
            ),
            WorkflowNodeDefinition(
                "audio-tags", "audio.annotate", depends_on=("audio",)
            ),
            WorkflowNodeDefinition(
                "evidence",
                "evidence.align",
                depends_on=("frames", "transcript", "audio-tags"),
            ),
            WorkflowNodeDefinition(
                "knowledge",
                "analysis.semantic_extract",
                depends_on=("evidence",),
                estimated_cost_micros=100,
            ),
        ),
    )
    book_script = WorkflowDefinition(
        workflow_key="factory.book-script.v1",
        name="拆书、剧本与创作圣经",
        schema_revision="workflow.v1",
        nodes=(
            WorkflowNodeDefinition("book", "book.split"),
            WorkflowNodeDefinition(
                "chapters",
                "chapter.enrich",
                depends_on=("book",),
                estimated_cost_micros=100,
            ),
            *tuple(
                WorkflowNodeDefinition(
                    f"bible-{kind}",
                    f"bible.{kind}.generate",
                    depends_on=("chapters",),
                    estimated_cost_micros=100,
                )
                for kind in ("story", "character", "world", "style")
            ),
            WorkflowNodeDefinition(
                "storyboard",
                "storyboard.generate",
                depends_on=(
                    "bible-story",
                    "bible-character",
                    "bible-world",
                    "bible-style",
                ),
                estimated_cost_micros=100,
            ),
        ),
    )
    assets_keyframes = WorkflowDefinition(
        workflow_key="factory.assets-keyframes.v1",
        name="资产与关键帧",
        schema_revision="workflow.v1",
        nodes=(
            WorkflowNodeDefinition("asset-plan", "asset.plan"),
            WorkflowNodeDefinition(
                "character",
                "asset.character.generate",
                depends_on=("asset-plan",),
                parameter_snapshot={"seed": 1001},
            ),
            WorkflowNodeDefinition(
                "scene",
                "asset.scene.generate",
                depends_on=("asset-plan",),
                parameter_snapshot={"seed": 1002},
            ),
            WorkflowNodeDefinition(
                "prop",
                "asset.prop.generate",
                depends_on=("asset-plan",),
                parameter_snapshot={"seed": 1003},
            ),
            WorkflowNodeDefinition(
                "asset-gate",
                "qc.gate.asset",
                kind=WorkflowNodeKind.QUALITY_GATE,
                depends_on=("character", "scene", "prop"),
            ),
            WorkflowNodeDefinition(
                "prompt",
                "prompt.compile",
                depends_on=("asset-gate",),
            ),
            WorkflowNodeDefinition(
                "keyframe",
                "keyframe.generate",
                depends_on=("prompt",),
                parameter_snapshot={"seed": 2001},
            ),
            WorkflowNodeDefinition(
                "keyframe-gate",
                "qc.gate.keyframe",
                kind=WorkflowNodeKind.QUALITY_GATE,
                depends_on=("keyframe",),
            ),
        ),
    )
    clip = WorkflowDefinition(
        workflow_key="factory.clip.v1",
        name="单镜头生成与质检",
        schema_revision="workflow.v1",
        nodes=(
            WorkflowNodeDefinition(
                "clip",
                "video.generate",
                structured_inputs={"mode": "i2v"},
                parameter_snapshot={"seed": 3001},
                estimated_cost_micros=500,
            ),
            WorkflowNodeDefinition(
                "clip-gate",
                "qc.gate.clip",
                kind=WorkflowNodeKind.QUALITY_GATE,
                depends_on=("clip",),
            ),
        ),
    )
    final_delivery = WorkflowDefinition(
        workflow_key="factory.final-delivery.v1",
        name="成片组装、全局质检与交付",
        schema_revision="workflow.v1",
        nodes=(
            WorkflowNodeDefinition("assemble", "final.assemble"),
            WorkflowNodeDefinition(
                "final-gate",
                "qc.gate.final",
                kind=WorkflowNodeKind.QUALITY_GATE,
                depends_on=("assemble",),
            ),
            WorkflowNodeDefinition(
                "delivery",
                "delivery.publish",
                kind=WorkflowNodeKind.DELIVERY,
                depends_on=("final-gate",),
            ),
        ),
    )
    two_shot = WorkflowDefinition(
        workflow_key="factory.two-shot.v1",
        name="两镜头真实垂直链",
        schema_revision="workflow.v1",
        nodes=(
            WorkflowNodeDefinition(
                "bootstrap",
                "two_shot.bootstrap",
                structured_inputs={
                    "schema_version": "factory.two-shot-input.v1"
                },
            ),
            WorkflowNodeDefinition(
                "plan.001",
                "two_shot.plan",
                depends_on=("bootstrap",),
                structured_inputs={"shot_index": 0},
                parameter_snapshot={"video_seed": 4201},
            ),
            WorkflowNodeDefinition(
                "plan.002",
                "two_shot.plan",
                depends_on=("bootstrap",),
                structured_inputs={"shot_index": 1},
                parameter_snapshot={"video_seed": 4202},
            ),
            WorkflowNodeDefinition(
                "assembly-plan",
                "assembly.plan",
                depends_on=("bootstrap",),
            ),
            WorkflowNodeDefinition(
                "first-frame.001",
                "keyframe.generate",
                depends_on=("plan.001",),
                structured_inputs={"frame_role": "first_frame"},
                parameter_snapshot={"seed": 4101},
            ),
            WorkflowNodeDefinition(
                "last-frame.001",
                "keyframe.generate",
                depends_on=("plan.001",),
                structured_inputs={"frame_role": "last_frame"},
                parameter_snapshot={"seed": 4111},
            ),
            WorkflowNodeDefinition(
                "first-frame.002",
                "keyframe.generate",
                depends_on=("plan.002",),
                structured_inputs={"frame_role": "first_frame"},
                parameter_snapshot={"seed": 4102},
            ),
            WorkflowNodeDefinition(
                "last-frame.002",
                "keyframe.generate",
                depends_on=("plan.002",),
                structured_inputs={"frame_role": "last_frame"},
                parameter_snapshot={"seed": 4112},
            ),
            WorkflowNodeDefinition(
                "generation.001",
                "generation.bind",
                depends_on=(
                    "plan.001",
                    "first-frame.001",
                    "last-frame.001",
                ),
            ),
            WorkflowNodeDefinition(
                "generation.002",
                "generation.bind",
                depends_on=(
                    "plan.002",
                    "first-frame.002",
                    "last-frame.002",
                ),
            ),
            WorkflowNodeDefinition(
                "prompt.001",
                "prompt.compile",
                depends_on=("plan.001", "generation.001"),
            ),
            WorkflowNodeDefinition(
                "prompt.002",
                "prompt.compile",
                depends_on=("plan.002", "generation.002"),
            ),
            WorkflowNodeDefinition(
                "clip.001",
                "video.generate",
                depends_on=(
                    "plan.001",
                    "generation.001",
                    "prompt.001",
                    "first-frame.001",
                    "last-frame.001",
                ),
                structured_input_bindings={
                    "mode": "/shots/0/generation/mode"
                },
                parameter_snapshot={"seed": 4201},
                estimated_cost_micros=500,
            ),
            WorkflowNodeDefinition(
                "clip.002",
                "video.generate",
                depends_on=(
                    "plan.002",
                    "generation.002",
                    "prompt.002",
                    "first-frame.002",
                    "last-frame.002",
                ),
                structured_input_bindings={
                    "mode": "/shots/1/generation/mode"
                },
                parameter_snapshot={"seed": 4202},
                estimated_cost_micros=500,
            ),
            WorkflowNodeDefinition(
                "clip-gate.001",
                "qc.gate.clip",
                kind=WorkflowNodeKind.QUALITY_GATE,
                depends_on=("clip.001",),
            ),
            WorkflowNodeDefinition(
                "clip-gate.002",
                "qc.gate.clip",
                kind=WorkflowNodeKind.QUALITY_GATE,
                depends_on=("clip.002",),
            ),
            WorkflowNodeDefinition(
                "assemble",
                "final.assemble",
                depends_on=(
                    "assembly-plan",
                    "clip-gate.001",
                    "clip-gate.002",
                ),
            ),
            WorkflowNodeDefinition(
                "final-gate",
                "qc.gate.final",
                kind=WorkflowNodeKind.QUALITY_GATE,
                depends_on=("assemble",),
            ),
            WorkflowNodeDefinition(
                "delivery",
                "delivery.publish",
                kind=WorkflowNodeKind.DELIVERY,
                depends_on=("final-gate",),
            ),
        ),
    )
    shidu_trial = shidu_trial_workflow_definition()
    shidu_h3 = h3_shidu_workflow_definition(sequence_count=2)
    return WorkflowCatalog(
        (
            video_learning,
            book_script,
            assets_keyframes,
            clip,
            final_delivery,
            two_shot,
            shidu_trial,
            shidu_h3,
        )
    )


__all__ = [
    "MaterializedWorkflow",
    "WorkflowCatalog",
    "WorkflowCatalogError",
    "WorkflowDefinition",
    "WorkflowMaterializer",
    "WorkflowNodeDefinition",
    "WorkflowNodeKind",
    "default_workflow_catalog",
    "h3_shidu_workflow_definition",
    "shidu_trial_workflow_definition",
]
