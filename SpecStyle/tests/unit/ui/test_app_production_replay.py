from __future__ import annotations

from types import SimpleNamespace
import sys

import pytest

from specstyle.ui.app import UiServices, create_app
from specstyle.ui.view_models import SpecEditorView


class _Context:
    def __enter__(self) -> _Context:
        return self

    def __exit__(self, *_args: object) -> None:
        pass


class _Blocks(_Context):
    def __init__(self, **_kwargs: object) -> None:
        self.queue_options: dict[str, object] | None = None

    def queue(self, **kwargs: object) -> _Blocks:
        self.queue_options = kwargs
        return self


class _Component:
    def __init__(self, label: str = "", **_kwargs: object) -> None:
        self.label = label
        self.event: dict[str, object] | None = None

    def click(
        self,
        fn: object,
        *,
        inputs: list[object] | None = None,
        outputs: list[object] | None = None,
        **kwargs: object,
    ) -> None:
        self.event = {
            "fn": fn,
            "inputs": inputs or [],
            "outputs": outputs or [],
            **kwargs,
        }


def _fake_gradio(buttons: list[_Component]) -> object:
    def button(label: str, **kwargs: object) -> _Component:
        component = _Component(label, **kwargs)
        buttons.append(component)
        return component

    return SimpleNamespace(
        Blocks=_Blocks,
        Tab=lambda *_args, **_kwargs: _Context(),
        Markdown=lambda *_args, **_kwargs: _Component(),
        Textbox=lambda **kwargs: _Component(**kwargs),
        Button=button,
        File=lambda **kwargs: _Component(**kwargs),
        Gallery=lambda **kwargs: _Component(**kwargs),
        Dropdown=lambda **kwargs: _Component(**kwargs),
        Slider=lambda **kwargs: _Component(**kwargs),
    )


def test_replay_button_uses_nine_form_inputs_and_run_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    buttons: list[_Component] = []
    monkeypatch.setitem(sys.modules, "gradio", _fake_gradio(buttons))
    received: list[tuple[object, ...]] = []

    def run_replay(*args: object) -> str:
        received.append(args)
        return "EXACT"

    services = UiServices(
        lambda _text: SpecEditorView("1.0", "spec", True, (), "a" * 64),
        run_replay=run_replay,  # type: ignore[arg-type]
    )

    app = create_app(services)
    replay = next(item for item in buttons if item.label == "Replay")
    assert replay.event is not None
    assert len(replay.event["inputs"]) == 9
    assert replay.event["concurrency_id"] == "production-run"
    assert replay.event["concurrency_limit"] == 2
    handler = replay.event["fn"]
    assert callable(handler)

    output = handler(
        "source",
        "style",
        "spec",
        "positive",
        "negative",
        "",
        "",
        "",
        "not_applicable",
    )

    assert output == "EXACT"
    assert received == [
        (
            "source",
            "style",
            "spec",
            "positive",
            "negative",
            None,
            None,
            None,
            "not_applicable",
        )
    ]
    assert app.queue_options == {"default_concurrency_limit": 1}
