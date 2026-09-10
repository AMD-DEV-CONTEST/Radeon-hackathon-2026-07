import dataclasses
import random
from concurrent.futures import ThreadPoolExecutor

import pytest
from PIL import Image

from tests.unit.generation.test_requests import _request

from specstyle.errors import DomainError, InfrastructureError
from specstyle.domain.identifiers import AttemptId
from specstyle.generation.fake_backend import FakeBackend
from specstyle.generation.requests import GenerationParameters


def test_fake_backend_is_deterministic_across_fresh_instances() -> None:
    request = _request()
    first = FakeBackend().generate(request)
    second = FakeBackend().generate(request)
    assert (first.content, first.ref.sha256) == (second.content, second.ref.sha256)


def test_fake_backend_claims_attempt_before_rendering() -> None:
    backend = FakeBackend()
    request = _request()
    backend.generate(request)
    with pytest.raises(DomainError):
        backend.generate(request)


def test_fake_backend_uses_init_false_instance_claim_state() -> None:
    fields = {field.name: field for field in dataclasses.fields(FakeBackend)}
    assert fields["_lock"].init is False
    assert fields["_seen_attempts"].init is False


def test_fake_backend_allows_only_one_concurrent_attempt_claim() -> None:
    backend = FakeBackend()
    request = _request()
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: _generate(backend, request), range(2)))
    assert results.count("ok") == results.count("claimed") == 1


def test_fake_backend_keeps_claim_when_rendering_fails() -> None:
    class FailingBackend(FakeBackend):
        def _render(self, request: object) -> bytes:
            raise RuntimeError("render failure")

    backend = FailingBackend()
    request = _request()
    with pytest.raises(RuntimeError, match="render failure"):
        backend.generate(request)
    with pytest.raises(DomainError, match="claimed"):
        backend.generate(request)


def test_fake_backend_attempt_changes_artifact_but_not_content_or_random_state() -> (
    None
):
    before = random.getstate()
    first = FakeBackend().generate(_request())
    second = FakeBackend().generate(
        _request(
            attempt_id=__import__(
                "specstyle.domain.identifiers", fromlist=["AttemptId"]
            ).AttemptId("attempt2")
        )
    )
    assert first.content == second.content
    assert first.ref.artifact_id != second.ref.artifact_id
    assert random.getstate() == before


def test_fake_backend_parameter_override_changes_content_without_changing_seed() -> (
    None
):
    base = _request()
    override = _request(
        parent_attempt_id=AttemptId("parent"),
        execution_parameters=GenerationParameters(0.4, 0.45, 0.7),
    )

    first = FakeBackend().generate(base)
    second = FakeBackend().generate(override)

    assert override.seed == base.seed
    assert second.content != first.content


@pytest.mark.parametrize(
    "parameters",
    (
        GenerationParameters(0.4, 0.45, 0.7),
        GenerationParameters(0.55, 0.4, 0.7),
        GenerationParameters(0.55, 0.45, 0.6),
    ),
)
def test_fake_backend_changes_content_for_each_parameter_override(
    parameters: GenerationParameters,
) -> None:
    base = _request()
    override = _request(
        parent_attempt_id=AttemptId("parent"), execution_parameters=parameters
    )

    first = FakeBackend().generate(base)
    second = FakeBackend().generate(override)

    assert override.seed == base.seed
    assert second.content != first.content


def test_fake_backend_output_is_clean_single_frame_rgb_png_at_graph_resolution() -> (
    None
):
    artifact = FakeBackend().generate(_request())

    with Image.open(__import__("io").BytesIO(artifact.content)) as image:
        assert (image.format, image.mode, image.size, image.n_frames) == (
            "PNG",
            "RGB",
            _request().graph.resolution,
            1,
        )
        assert image.info == {}


def test_fake_backend_maps_successful_render_close_failure_to_infrastructure_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()

    def fail_close(image: Image.Image) -> None:
        raise RuntimeError("close sentinel")

    monkeypatch.setattr(Image.Image, "close", fail_close)
    with pytest.raises(InfrastructureError, match="image processing failed") as raised:
        FakeBackend().generate(request)
    assert "close sentinel" not in str(raised.value)


def _generate(backend: FakeBackend, request: object) -> str:
    try:
        backend.generate(request)  # type: ignore[arg-type]
    except DomainError:
        return "claimed"
    return "ok"
