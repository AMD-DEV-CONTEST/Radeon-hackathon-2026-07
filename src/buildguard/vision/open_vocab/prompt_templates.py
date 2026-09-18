"""Conservative prompt rendering using only configured labels."""

from __future__ import annotations


class PromptTemplateRegistry:
    """Render fixed templates without accepting arbitrary prompt instructions."""

    def __init__(self, templates: list[str] | None = None) -> None:
        self.templates = templates or ["{label}"]
        if any(template.count("{label}") != 1 for template in self.templates):
            raise ValueError("Every open-vocabulary template must contain {label} exactly once")

    def render(self, labels: list[str]) -> list[str]:
        prompts: list[str] = []
        for label in labels:
            for template in self.templates:
                prompt = template.format(label=label)
                if prompt not in prompts:
                    prompts.append(prompt)
        return prompts

