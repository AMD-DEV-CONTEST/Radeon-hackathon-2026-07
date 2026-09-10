from io import BytesIO

import pytest
from PIL import Image, PngImagePlugin

from specstyle.domain.artifacts import ArtifactRef
from specstyle.domain.identifiers import ArtifactId, AttemptId
from specstyle.errors import DomainError, InfrastructureError
from specstyle.generation.protocols import build_control_input, run_generation
from specstyle.generation.fake_backend import FakeBackend
from specstyle.generation.requests import GenerationParameters, PreparedControlInput
from specstyle.observability.hashing import hash_bytes
from tests.unit.generation.test_requests import _request


def test_runner_propagates_declared_errors_without_wrapping() -> None:
    class Backend:
        def generate(self, request: object) -> object:
            raise DomainError("expected")

    with pytest.raises(DomainError, match="expected"):
        run_generation(Backend(), _request())


def test_runner_wraps_unexpected_backend_exception() -> None:
    class Backend:
        def generate(self, request: object) -> object:
            raise RuntimeError("private prompt must not leak")

    with pytest.raises(InfrastructureError, match="backend failure"):
        run_generation(Backend(), _request())


def test_builder_wraps_unexpected_builder_exception() -> None:
    class Builder:
        def build(self, source: object, graph: object) -> object:
            raise RuntimeError("unexpected")

    with pytest.raises(InfrastructureError, match="builder failure"):
        request = _request()
        build_control_input(Builder(), request.source, request.graph)


def test_builder_returns_a_revalidated_successful_control_input() -> None:
    request = _request()

    class Builder:
        def build(self, source: object, graph: object) -> object:
            return PreparedControlInput("canny", request.source)

    result = build_control_input(Builder(), request.source, request.graph)
    assert result == PreparedControlInput("canny", request.source)


def test_runner_returns_a_revalidated_successful_generated_artifact() -> None:
    request = _request()
    expected = FakeBackend().generate(request)

    class Backend:
        def generate(self, value: object) -> object:
            return expected

    assert run_generation(Backend(), request) == expected


def test_runner_rejects_forged_generated_artifact_as_contract_violation() -> None:
    request = _request()
    artifact = FakeBackend().generate(request)
    object.__setattr__(artifact.ref, "sha256", artifact.ref.sha256.value)

    class Backend:
        def generate(self, request: object) -> object:
            return artifact

    with pytest.raises(InfrastructureError, match="contract violation"):
        run_generation(Backend(), request)  # type: ignore[arg-type]


def test_builder_rejects_forged_source_before_calling_external_builder() -> None:
    request = _request()
    object.__setattr__(request.source, "sha256", "forged")

    class Builder:
        called = False

        def build(self, source: object, graph: object) -> PreparedControlInput:
            self.called = True
            return PreparedControlInput("canny", request.source)

    builder = Builder()
    with pytest.raises(InfrastructureError, match="contract violation"):
        build_control_input(builder, request.source, request.graph)
    assert builder.called is False


def test_builder_rejects_forged_return_instead_of_rebuilding_it() -> None:
    request = _request()
    returned = PreparedControlInput("canny", request.source)
    object.__setattr__(returned.image, "sha256", "forged")

    class Builder:
        def build(self, source: object, graph: object) -> PreparedControlInput:
            return returned

    with pytest.raises(InfrastructureError, match="contract violation"):
        build_control_input(Builder(), request.source, request.graph)


def test_runner_rejects_forged_request_before_calling_backend() -> None:
    request = _request()
    object.__setattr__(request, "request_hash", "forged")

    class Backend:
        called = False

        def generate(self, value: object) -> object:
            self.called = True
            return FakeBackend().generate(_request())

    backend = Backend()
    with pytest.raises(InfrastructureError, match="contract violation"):
        run_generation(backend, request)
    assert backend.called is False


def test_runner_rejects_forged_execution_parameters_before_calling_backend() -> None:
    request = _request(
        parent_attempt_id=AttemptId("parent"),
        execution_parameters=GenerationParameters(0.4, 0.45, 0.7),
    )
    object.__setattr__(request.execution_parameters, "ip_adapter_scale", "forged")

    class Backend:
        called = False

        def generate(self, value: object) -> object:
            self.called = True
            raise AssertionError("forged parameters reached backend")

    backend = Backend()
    with pytest.raises(InfrastructureError, match="contract violation"):
        run_generation(backend, request)
    assert backend.called is False


def test_runner_rebuilds_request_with_execution_parameters_intact() -> None:
    request = _request(
        parent_attempt_id=AttemptId("parent"),
        execution_parameters=GenerationParameters(0.4, 0.45, 0.7),
    )

    class Backend:
        def generate(self, value: object) -> object:
            assert value.execution_parameters == GenerationParameters(0.4, 0.45, 0.7)
            return FakeBackend().generate(value)

    artifact = run_generation(Backend(), request)
    assert artifact.generation_fingerprint == request.generation_fingerprint


def test_runner_rejects_pre_forged_prompt_before_calling_backend() -> None:
    request = _request()
    object.__setattr__(request.prompt, "positive", " forged prompt")

    class Backend:
        called = False

        def generate(self, value: object) -> object:
            self.called = True
            raise AssertionError("forged prompt reached backend")

    backend = Backend()
    with pytest.raises(InfrastructureError, match="contract violation") as raised:
        run_generation(backend, request)
    assert backend.called is False
    assert "forged prompt" not in str(raised.value)


def test_runner_rejects_forged_artifact_identifier_instead_of_rebuilding_it() -> None:
    request = _request()
    artifact = FakeBackend().generate(request)
    object.__setattr__(artifact.ref, "artifact_id", "forged-artifact")

    class Backend:
        def generate(self, value: object) -> object:
            return artifact

    with pytest.raises(InfrastructureError, match="contract violation"):
        run_generation(Backend(), request)


@pytest.mark.parametrize(
    "mutate",
    (
        lambda request: object.__setattr__(request.prompt.template_pin, "sha256", "x"),
        lambda request: object.__setattr__(request.source.snapshot, "plan", "x"),
        lambda request: object.__setattr__(request.source, "sha256", "x"),
        lambda request: object.__setattr__(request, "request_hash", "x"),
        lambda request: object.__setattr__(request, "generation_fingerprint", "x"),
    ),
)
def test_runner_rejects_each_forged_request_material(
    mutate: object,
) -> None:
    request = _request()
    mutate(request)

    class Backend:
        def generate(self, value: object) -> object:
            raise AssertionError("forged request reached backend")

    with pytest.raises(InfrastructureError, match="contract violation"):
        run_generation(Backend(), request)


@pytest.mark.parametrize(
    "mutate",
    (
        lambda artifact: object.__setattr__(artifact, "ref", "x"),
        lambda artifact: object.__setattr__(artifact.ref, "artifact_id", "x"),
        lambda artifact: object.__setattr__(artifact.ref, "sha256", "x"),
        lambda artifact: object.__setattr__(artifact, "content", b"x"),
        lambda artifact: object.__setattr__(artifact, "request_hash", "x"),
        lambda artifact: object.__setattr__(artifact, "generation_fingerprint", "x"),
    ),
)
def test_runner_rejects_each_forged_result_material(mutate: object) -> None:
    request = _request()
    artifact = FakeBackend().generate(request)
    mutate(artifact)

    class Backend:
        def generate(self, value: object) -> object:
            return artifact

    with pytest.raises(InfrastructureError, match="contract violation"):
        run_generation(Backend(), request)


@pytest.mark.parametrize("error_type", (DomainError, InfrastructureError))
def test_builder_propagates_declared_errors(error_type: type[Exception]) -> None:
    request = _request()

    class Builder:
        def build(self, source: object, graph: object) -> object:
            raise error_type("declared")

    with pytest.raises(error_type, match="declared"):
        build_control_input(Builder(), request.source, request.graph)


@pytest.mark.parametrize("error_type", (DomainError, InfrastructureError))
def test_runner_propagates_declared_errors(error_type: type[Exception]) -> None:
    class Backend:
        def generate(self, request: object) -> object:
            raise error_type("declared")

    with pytest.raises(error_type, match="declared"):
        run_generation(Backend(), _request())


@pytest.mark.parametrize("operation", ("builder", "backend"))
def test_protocol_boundaries_do_not_catch_base_exception(operation: str) -> None:
    request = _request()
    if operation == "builder":

        class Builder:
            def build(self, source: object, graph: object) -> object:
                raise KeyboardInterrupt()

        with pytest.raises(KeyboardInterrupt):
            build_control_input(Builder(), request.source, request.graph)
    else:

        class Backend:
            def generate(self, value: object) -> object:
                raise KeyboardInterrupt()

        with pytest.raises(KeyboardInterrupt):
            run_generation(Backend(), request)


@pytest.mark.parametrize("field", ("sha256", "source", "snapshot"))
def test_builder_rejects_forged_prepared_image_fields(field: str) -> None:
    request = _request()
    source = request.source
    object.__setattr__(source, field, "forged")

    class Builder:
        def build(self, value: object, graph: object) -> object:
            return PreparedControlInput("canny", request.source)

    with pytest.raises(InfrastructureError, match="contract violation"):
        build_control_input(Builder(), source, request.graph)


def test_builder_rejects_wrong_result_type_as_contract_violation() -> None:
    request = _request()

    class Builder:
        def build(self, source: object, graph: object) -> object:
            return object()

    with pytest.raises(InfrastructureError, match="contract violation"):
        build_control_input(Builder(), request.source, request.graph)


def _artifact(request: object, content: bytes) -> object:
    return __import__(
        "specstyle.generation.protocols", fromlist=["GeneratedArtifact"]
    ).GeneratedArtifact(
        ArtifactRef(ArtifactId("artifact"), hash_bytes(content)),
        content,
        request.request_hash,
        request.generation_fingerprint,
    )


@pytest.mark.parametrize("mode", ("RGBA", "L"))
def test_runner_rejects_non_rgb_png_result(mode: str) -> None:
    request = _request()
    output = BytesIO()
    Image.new(mode, request.graph.resolution).save(output, "PNG")
    artifact = _artifact(request, output.getvalue())

    class Backend:
        def generate(self, value: object) -> object:
            return artifact

    with pytest.raises(InfrastructureError, match="contract violation"):
        run_generation(Backend(), request)


def test_runner_rejects_png_result_with_text_metadata() -> None:
    request = _request()
    output = BytesIO()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("secret", "must-not-pass")
    Image.new("RGB", request.graph.resolution).save(output, "PNG", pnginfo=metadata)
    artifact = _artifact(request, output.getvalue())

    class Backend:
        def generate(self, value: object) -> object:
            return artifact

    with pytest.raises(InfrastructureError, match="contract violation"):
        run_generation(Backend(), request)


def test_runner_rejects_non_png_result() -> None:
    request = _request()
    output = BytesIO()
    Image.new("RGB", request.graph.resolution).save(output, "JPEG")
    artifact = _artifact(request, output.getvalue())

    class Backend:
        def generate(self, value: object) -> object:
            return artifact

    with pytest.raises(InfrastructureError, match="contract violation"):
        run_generation(Backend(), request)


def test_runner_rejects_wrong_size_and_animated_png_results() -> None:
    request = _request()
    wrong_size = BytesIO()
    Image.new("RGB", (64, 64)).save(wrong_size, "PNG")
    animated = BytesIO()
    first = Image.new("RGB", request.graph.resolution)
    first.save(
        animated,
        "PNG",
        save_all=True,
        append_images=[Image.new("RGB", request.graph.resolution, "blue")],
    )

    for content in (wrong_size.getvalue(), animated.getvalue()):
        artifact = _artifact(request, content)

        class Backend:
            def generate(self, value: object) -> object:
                return artifact

        with pytest.raises(InfrastructureError, match="contract violation"):
            run_generation(Backend(), request)


def test_runner_maps_output_decompression_bomb_warning_to_contract_violation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    artifact = FakeBackend().generate(request)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)

    class Backend:
        def generate(self, value: object) -> object:
            return artifact

    with pytest.raises(InfrastructureError, match="contract violation"):
        run_generation(Backend(), request)
