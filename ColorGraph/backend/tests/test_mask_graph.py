import pytest
import torch

from colorgraph.grading.masks import (
    evaluate_mask_expression,
    mask_expression_operands,
)


def test_mask_graph_combines_semantic_targets_with_fuzzy_boolean_logic() -> None:
    sky = torch.tensor([[[0.9, 0.8], [0.2, 0.0]]])
    mountain = torch.tensor([[[0.0, 0.6], [0.7, 0.0]]])
    masks = {"mask_sky": sky, "mask_mountain": mountain}

    result = evaluate_mask_expression(
        "sky AND NOT mountain",
        masks,
        {"sky": "mask_sky", "mountain": "mask_mountain"},
    )

    assert torch.allclose(
        result,
        torch.tensor([[[0.9, 0.4], [0.2, 0.0]]]),
    )
    assert mask_expression_operands("(sky OR water) AND NOT mountain") == {
        "sky",
        "water",
        "mountain",
    }


def test_mask_graph_rejects_unknown_or_malformed_expressions() -> None:
    masks = {"mask_sky": torch.ones(1, 2, 2)}
    with pytest.raises(ValueError, match="unknown"):
        evaluate_mask_expression("sky AND sun", masks, {"sky": "mask_sky"})
    with pytest.raises(ValueError, match="requires two"):
        evaluate_mask_expression("sky AND", masks, {"sky": "mask_sky"})
    with pytest.raises(ValueError, match="unbalanced"):
        evaluate_mask_expression("(sky", masks, {"sky": "mask_sky"})
