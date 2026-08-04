from __future__ import annotations

import json
import types
from dataclasses import MISSING, asdict, dataclass, fields, is_dataclass
from datetime import date
from typing import (
    Any,
    Callable,
    Generic,
    Mapping,
    TypeVar,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

from .models import (
    AvailabilityInput,
    AvailabilityResult,
    BookingListResult,
    BookingResult,
    CreateServiceTicketInput,
    DeletePreferenceInput,
    DeletePreferenceResult,
    GetPreferencesInput,
    HoldBookingInput,
    MemoryConsentResult,
    ModifyBookingInput,
    MyBookingsInput,
    PreferenceResult,
    PreferencesResult,
    QuoteInput,
    QuoteResult,
    RememberPreferenceInput,
    ServiceTicketResult,
    SetMemoryConsentInput,
    ToolEffect,
    UserContext,
    ValidationError,
)
from .service import HotelService
from .storage import stable_hash


InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


_ROOM_TYPES = ["standard", "deluxe", "suite"]
_FIELD_CONSTRAINTS: dict[str, dict[str, dict[str, Any]]] = {
    "hotel.check_availability": {
        "check_in": {"format": "date"},
        "check_out": {"format": "date"},
        "guests": {"minimum": 1},
        "room_type": {
            "anyOf": [
                {"type": "string", "enum": _ROOM_TYPES},
                {"type": "null"},
            ]
        },
    },
    "hotel.quote_stay": {
        "room_type": {"type": "string", "enum": _ROOM_TYPES},
        "check_in": {"format": "date"},
        "check_out": {"format": "date"},
        "guests": {"minimum": 1},
    },
    "hotel.hold_booking": {
        "room_type": {"type": "string", "enum": _ROOM_TYPES},
        "check_in": {"format": "date"},
        "check_out": {"format": "date"},
        "guests": {"minimum": 1},
    },
    "hotel.modify_booking": {
        "booking_id": {"minLength": 1},
        "room_type": {
            "anyOf": [
                {"type": "string", "enum": _ROOM_TYPES},
                {"type": "null"},
            ]
        },
        "check_in": {
            "anyOf": [
                {"type": "string", "format": "date"},
                {"type": "null"},
            ]
        },
        "check_out": {
            "anyOf": [
                {"type": "string", "format": "date"},
                {"type": "null"},
            ]
        },
        "guests": {
            "anyOf": [
                {"type": "integer", "minimum": 1},
                {"type": "null"},
            ]
        },
    },
    "hotel.create_service_ticket": {
        "booking_id": {"minLength": 1},
        "category": {
            "enum": [
                "accessibility",
                "cleaning",
                "maintenance",
                "room_service",
                "transport",
                "other",
            ]
        },
        "description": {"minLength": 1, "maxLength": 1_000},
    },
    "memory.remember_preference": {
        "key": {
            "enum": [
                "accessibility",
                "bed_type",
                "floor",
                "language",
                "pillow",
                "quiet_room",
            ]
        },
        "value": {"minLength": 1, "maxLength": 200},
    },
    "memory.delete_preference": {
        "key": {
            "enum": [
                "accessibility",
                "bed_type",
                "floor",
                "language",
                "pillow",
                "quiet_room",
            ]
        }
    },
}


def _json_type(annotation: Any) -> dict[str, Any]:
    origin = get_origin(annotation)
    arguments = get_args(annotation)
    if origin in {Union, types.UnionType}:
        non_null = [item for item in arguments if item is not type(None)]
        if len(non_null) == 1 and len(non_null) != len(arguments):
            return {"anyOf": [_json_type(non_null[0]), {"type": "null"}]}
        return {"anyOf": [_json_type(item) for item in arguments]}
    if origin in {list, tuple}:
        item_type = arguments[0] if arguments else Any
        return {"type": "array", "items": _json_type(item_type)}
    if annotation is str:
        return {"type": "string"}
    if annotation is bool:
        return {"type": "boolean"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if isinstance(annotation, type) and is_dataclass(annotation):
        type_hints = get_type_hints(annotation)
        dataclass_fields = fields(annotation)
        return {
            "type": "object",
            "properties": {
                field.name: _json_type(type_hints.get(field.name, Any))
                for field in dataclass_fields
            },
            "required": [
                field.name
                for field in dataclass_fields
                if field.default is MISSING and field.default_factory is MISSING
            ],
            "additionalProperties": False,
        }
    return {}


def _matches_type(value: Any, annotation: Any) -> bool:
    if annotation is Any:
        return True
    origin = get_origin(annotation)
    arguments = get_args(annotation)
    if origin in {Union, types.UnionType}:
        return any(_matches_type(value, item) for item in arguments)
    if origin is list:
        item_type = arguments[0] if arguments else Any
        return isinstance(value, list) and all(
            _matches_type(item, item_type) for item in value
        )
    if origin is tuple:
        item_type = arguments[0] if arguments else Any
        return isinstance(value, tuple) and all(
            _matches_type(item, item_type) for item in value
        )
    if annotation is type(None):
        return value is None
    if annotation is bool:
        return type(value) is bool
    if annotation is int:
        return type(value) is int
    if annotation is float:
        return type(value) in {int, float}
    if isinstance(annotation, type):
        return isinstance(value, annotation)
    return False


def _validate_request_types(spec: "ToolSpec[Any, Any]", request: Any) -> None:
    type_hints = get_type_hints(spec.input_type)
    for field in fields(spec.input_type):
        value = getattr(request, field.name)
        annotation = type_hints.get(field.name, Any)
        if not _matches_type(value, annotation):
            raise ValidationError(
                f"invalid input type for {spec.name}.{field.name}"
            )


def _active_constraints(constraints: Mapping[str, Any], value: Any) -> Mapping[str, Any]:
    alternatives = constraints.get("anyOf")
    if not isinstance(alternatives, list) or value is None:
        return constraints
    expected_type: str | None = None
    if type(value) is bool:
        expected_type = "boolean"
    elif type(value) is int:
        expected_type = "integer"
    elif type(value) is float:
        expected_type = "number"
    elif isinstance(value, str):
        expected_type = "string"
    for alternative in alternatives:
        if isinstance(alternative, Mapping) and alternative.get("type") == expected_type:
            return alternative
    return constraints


def _validate_request_constraints(spec: "ToolSpec[Any, Any]", request: Any) -> None:
    values = asdict(request)
    for field_name, declared in _FIELD_CONSTRAINTS.get(spec.name, {}).items():
        value = values.get(field_name)
        if value is None:
            continue
        constraints = _active_constraints(declared, value)
        allowed = constraints.get("enum")
        if isinstance(allowed, list) and value not in allowed:
            raise ValidationError(f"invalid value for {spec.name}.{field_name}")
        minimum = constraints.get("minimum")
        if isinstance(minimum, (int, float)) and value < minimum:
            raise ValidationError(f"{spec.name}.{field_name} is below its minimum")
        if isinstance(value, str):
            normalized = value.strip()
            minimum_length = constraints.get("minLength")
            maximum_length = constraints.get("maxLength")
            if isinstance(minimum_length, int) and len(normalized) < minimum_length:
                raise ValidationError(f"{spec.name}.{field_name} is too short")
            if isinstance(maximum_length, int) and len(normalized) > maximum_length:
                raise ValidationError(f"{spec.name}.{field_name} is too long")
            if constraints.get("format") == "date":
                try:
                    date.fromisoformat(value)
                except ValueError as exc:
                    raise ValidationError(
                        f"{spec.name}.{field_name} must use ISO date format"
                    ) from exc
    if spec.name == "hotel.modify_booking" and all(
        values.get(name) is None
        for name in ("room_type", "check_in", "check_out", "guests")
    ):
        raise ValidationError("hotel.modify_booking requires at least one changed field")
    check_in = values.get("check_in")
    check_out = values.get("check_out")
    if isinstance(check_in, str) and isinstance(check_out, str):
        if date.fromisoformat(check_out) <= date.fromisoformat(check_in):
            raise ValidationError("check_out must be after check_in")


def _encode_output(value: Any) -> str:
    if hasattr(value, "to_dict"):
        data = value.to_dict()
    elif is_dataclass(value):
        data = asdict(value)
    else:
        raise TypeError("tool output must be a dataclass or implement to_dict")
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _decode_output(output_type: type[OutputT], encoded: str) -> OutputT:
    data = json.loads(encoded)
    factory = getattr(output_type, "from_dict", None)
    if factory is not None:
        return cast(OutputT, factory(data))
    return output_type(**data)


def _confirmation_binding_hash(
    payload_hash: str,
    preview: Mapping[str, Any],
) -> str:
    """Bind consent to both requested arguments and authoritative preview terms."""

    return stable_hash(
        {
            "payload_hash": payload_hash,
            "preview": dict(preview),
        }
    )


@dataclass(frozen=True, slots=True)
class ToolSpec(Generic[InputT, OutputT]):
    name: str
    description: str
    effect: ToolEffect
    input_type: type[InputT]
    output_type: type[OutputT]
    handler: Callable[[UserContext, InputT], OutputT]
    preview_handler: Callable[[UserContext, InputT], Mapping[str, Any]] | None = None

    def public_schema(self) -> dict[str, Any]:
        type_hints = get_type_hints(self.input_type)
        dataclass_fields = fields(self.input_type)
        properties = {
            field.name: _json_type(type_hints.get(field.name, Any))
            for field in dataclass_fields
        }
        for field in dataclass_fields:
            if field.default is not MISSING:
                properties[field.name]["default"] = field.default
        for field_name, constraints in _FIELD_CONSTRAINTS.get(self.name, {}).items():
            properties[field_name].update(constraints)
        required = [
            field.name
            for field in dataclass_fields
            if field.default is MISSING and field.default_factory is MISSING
        ]
        parameters: dict[str, Any] = {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        }
        if self.name == "hotel.modify_booking":
            parameters["anyOf"] = [
                {"required": [field_name]}
                for field_name in ("room_type", "check_in", "check_out", "guests")
            ]
        return {
            "name": self.name,
            "description": self.description,
            "effect": self.effect.value,
            "input_type": self.input_type.__name__,
            "output_type": self.output_type.__name__,
            "returns": _json_type(self.output_type),
            "fields": [field.name for field in dataclass_fields],
            "parameters": parameters,
            "requires_confirmation": self.effect is ToolEffect.WRITE,
            "requires_idempotency_key": self.effect is ToolEffect.WRITE,
        }


class ToolRegistry:
    """Typed local tool gateway with confirmation-bound, idempotent writes."""

    def __init__(self, service: HotelService) -> None:
        self.service = service
        self._tools: dict[str, ToolSpec[Any, Any]] = {}

    def register(self, spec: ToolSpec[Any, Any]) -> None:
        if spec.name in self._tools:
            raise ValueError(f"tool already registered: {spec.name}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec[Any, Any]:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ValidationError(f"unknown tool: {name}") from exc

    def schemas(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._tools[name].public_schema() for name in sorted(self._tools))

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    @staticmethod
    def _coerce_input(spec: ToolSpec[Any, Any], value: Any) -> Any:
        if isinstance(value, spec.input_type):
            typed_value = value
        elif isinstance(value, Mapping):
            try:
                typed_value = spec.input_type(**dict(value))
            except (TypeError, ValueError) as exc:
                raise ValidationError(f"invalid input for {spec.name}: {exc}") from exc
        else:
            raise ValidationError(
                f"{spec.name} expects {spec.input_type.__name__} or a mapping"
            )
        _validate_request_types(spec, typed_value)
        _validate_request_constraints(spec, typed_value)
        return typed_value

    def invoke(
        self,
        name: str,
        context: UserContext,
        request: Any,
        *,
        idempotency_key: str | None = None,
        confirmation_token: str | None = None,
    ) -> Any:
        spec = self.get(name)
        typed_request = self._coerce_input(spec, request)
        payload = asdict(typed_request)
        payload_hash = stable_hash(payload)

        if spec.effect is ToolEffect.READ:
            return spec.handler(context, typed_request)

        key = (idempotency_key or "").strip()
        if not key:
            raise ValidationError("write tools require a non-empty idempotency_key")
        if len(key) > 128:
            raise ValidationError("idempotency_key must not exceed 128 characters")

        if not confirmation_token:
            challenge = None
            with self.service.store.transaction():
                cached = self.service.store.get_idempotent_response(
                    context, name, key, payload_hash
                )
                if cached is not None:
                    return _decode_output(spec.output_type, cached)
                preview = (
                    dict(spec.preview_handler(context, typed_request))
                    if spec.preview_handler is not None
                    else {}
                )
                challenge = self.service.store.create_confirmation(
                    context,
                    name,
                    _confirmation_binding_hash(payload_hash, preview),
                    preview=preview,
                )
            assert challenge is not None
            raise challenge

        with self.service.store.transaction():
            cached = self.service.store.get_idempotent_response(
                context, name, key, payload_hash
            )
            if cached is not None:
                return _decode_output(spec.output_type, cached)
            current_preview = (
                dict(spec.preview_handler(context, typed_request))
                if spec.preview_handler is not None
                else {}
            )
            self.service.store.consume_confirmation(
                context,
                name,
                _confirmation_binding_hash(payload_hash, current_preview),
                confirmation_token,
            )
            result = spec.handler(context, typed_request)
            encoded = _encode_output(result)
            self.service.store.save_idempotent_response(
                context, name, key, payload_hash, encoded
            )
            return result


def build_tool_registry(service: HotelService) -> ToolRegistry:
    registry = ToolRegistry(service)
    specs = (
        ToolSpec(
            "hotel.check_availability",
            "Return local room inventory for a stay without exposing guest data.",
            ToolEffect.READ,
            AvailabilityInput,
            AvailabilityResult,
            service.check_availability,
        ),
        ToolSpec(
            "hotel.quote_stay",
            "Calculate a deterministic local quote in CNY.",
            ToolEffect.READ,
            QuoteInput,
            QuoteResult,
            service.quote,
        ),
        ToolSpec(
            "hotel.my_bookings",
            "List only the authenticated guest's bookings.",
            ToolEffect.READ,
            MyBookingsInput,
            BookingListResult,
            service.my_bookings,
        ),
        ToolSpec(
            "hotel.hold_booking",
            "Place a time-limited room hold for the authenticated guest.",
            ToolEffect.WRITE,
            HoldBookingInput,
            BookingResult,
            service.hold_booking,
            service.preview_hold_booking,
        ),
        ToolSpec(
            "hotel.modify_booking",
            "Modify a booking when invoked by its owner or hotel staff.",
            ToolEffect.WRITE,
            ModifyBookingInput,
            BookingResult,
            service.modify_booking,
            service.preview_modify_booking,
        ),
        ToolSpec(
            "hotel.create_service_ticket",
            "Create a service request for an owned booking; staff may act on any booking.",
            ToolEffect.WRITE,
            CreateServiceTicketInput,
            ServiceTicketResult,
            service.create_service_ticket,
            service.preview_service_ticket,
        ),
        ToolSpec(
            "memory.set_consent",
            "Explicitly enable or disable local preference memory; disabling erases it.",
            ToolEffect.WRITE,
            SetMemoryConsentInput,
            MemoryConsentResult,
            service.set_memory_consent,
        ),
        ToolSpec(
            "memory.remember_preference",
            "Store one allow-listed preference after explicit opt-in.",
            ToolEffect.WRITE,
            RememberPreferenceInput,
            PreferenceResult,
            service.remember_preference,
            service.preview_preference_storage,
        ),
        ToolSpec(
            "memory.get_preferences",
            "Read the authenticated guest's opted-in preferences.",
            ToolEffect.READ,
            GetPreferencesInput,
            PreferencesResult,
            service.get_preferences,
        ),
        ToolSpec(
            "memory.delete_preference",
            "Delete one preference owned by the authenticated guest.",
            ToolEffect.WRITE,
            DeletePreferenceInput,
            DeletePreferenceResult,
            service.delete_preference,
        ),
    )
    for spec in specs:
        registry.register(spec)
    return registry
