"""
Unit tests for Aetheris CLI model recipe picker logic.
Verifies recipe filtering, query matching, cursor movement, selection, and cancellation shortcuts.
"""

from aetheris_cli.commands.model_picker import ModelPicker, ModelRecipeSummary, PickerOutcomeKind


def sample_recipes():
    return [
        ModelRecipeSummary(id="qwen2.5:1.5b-q4_k_m", aliases=["qwen1.5b"], task="chat", preferred_engine="vte"),
        ModelRecipeSummary(id="qwen3.5:2b-q6_k", aliases=["qwen2b"], task="chat", preferred_engine="vte"),
        ModelRecipeSummary(id="llama3.1:8b-instruct-q4_k_m", aliases=["llama8b"], task="chat", preferred_engine="vte"),
    ]


def test_empty_query_matches_all():
    p = ModelPicker()
    assert len(p.filtered(sample_recipes())) == 3


def test_filter_matches_id_and_alias():
    p = ModelPicker(query="qwen")
    assert len(p.filtered(sample_recipes())) == 2

    p.query = "llama"
    assert len(p.filtered(sample_recipes())) == 1


def test_typing_resets_cursor():
    recipes = sample_recipes()
    p = ModelPicker(selected=2)
    p.on_key("q", recipes)
    assert p.query == "q"
    assert p.selected == 0


def test_enter_chooses_recipe():
    recipes = sample_recipes()
    p = ModelPicker(query="llama")
    outcome = p.on_key("enter", recipes)
    assert outcome.kind == PickerOutcomeKind.CHOSEN
    assert outcome.chosen_recipe is not None
    assert outcome.chosen_recipe.id == "llama3.1:8b-instruct-q4_k_m"


def test_esc_cancels():
    recipes = sample_recipes()
    p = ModelPicker()
    outcome = p.on_key("esc", recipes)
    assert outcome.kind == PickerOutcomeKind.CANCELLED
