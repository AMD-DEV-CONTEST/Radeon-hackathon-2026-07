"""Every provider Determinex can drive must be listable, or it may as well not be registered.

Ryan: "kimi, hf, vars ai, etc etc etc should all be configured in this." Two separate gaps sat
behind that, and only one of them was the obvious one.

The obvious gap: Kimi/Moonshot, Vertex, xAI, Mistral, Together, Cerebras and Fireworks had no rows,
so they could not be named anywhere -- not as a hive role, not as a chat participant's model, not by
the amplifier's router. Every one of them routes through the same LiteLLM call the existing rows
already used, so the capability was never missing; the row was.

The gap underneath it: `determinex_providers` had no machine-readable listing at all, only a
`print()` report for a human. So the seventeen providers it knew about were invisible to the app, and
registering a provider changed nothing a user could see. That is the same shape as the corpus that
was built but not queryable, and as `logged_in` reporting a fact nothing could act on.

`vars ai` was read as Vertex AI -- Google's other surface, which authenticates with GCP
service-account credentials rather than an AI Studio key. Keeping it a separate row from `gemini`
matters more than it looks: Google ended Code Assist for individual accounts on 2026-07-31 (measured
on this machine -- gemini-cli refused with IneligibleTierError while holding valid credentials), so
having both surfaces registered independently is what lets a Google model be reached at all when one
path is closed to an account.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT, _ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import determinex_providers as P  # noqa: E402

# Named because Ryan named them, plus the ones "etc etc etc" plainly covers.
EXPECTED = {
    "moonshot": "MOONSHOT_API_KEY",
    "huggingface": "HUGGINGFACE_API_KEY",
    "vertex_ai": "GOOGLE_APPLICATION_CREDENTIALS",
    "xai": "XAI_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "together_ai": "TOGETHERAI_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
    "fireworks_ai": "FIREWORKS_AI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}

# The short names a person would actually type.
ALIASES = {
    "kimi": "moonshot",
    "hf": "huggingface",
    "vertex": "vertex_ai",
    "vertexai": "vertex_ai",
    "grok": "xai",
    "together": "together_ai",
    "codestral": "mistral",
    "fireworks": "fireworks_ai",
}


class TestTheProvidersAreRegistered:
    @pytest.mark.parametrize("name,env_key", sorted(EXPECTED.items()))
    def test_the_provider_exists_and_names_its_key(self, name, env_key):
        provider = P._PROVIDERS.get(name)
        assert provider is not None, f"{name} is not registered, so it cannot be selected by name"
        assert provider.env_key == env_key, (
            f"{name} names {provider.env_key!r}; a wrong variable is worse than none, because the "
            f"user sets it and nothing changes"
        )
        assert provider.default_model, f"{name} has no default model"

    @pytest.mark.parametrize("alias,target", sorted(ALIASES.items()))
    def test_the_short_name_resolves(self, alias, target):
        provider = P._PROVIDERS.get(alias)
        assert provider is not None, f"{alias!r} resolves to nothing"
        assert provider.name == target

    def test_gemini_and_vertex_stay_separate(self):
        """Different auth surfaces. Collapsing them loses the only Google path left to an account
        whose Code Assist tier was ended."""
        assert P._PROVIDERS["gemini"].name != P._PROVIDERS["vertex_ai"].name
        assert P._PROVIDERS["gemini"].env_key == "GEMINI_API_KEY"
        assert P._PROVIDERS["vertex_ai"].env_key != "GEMINI_API_KEY"

    def test_every_provider_resolves_to_a_generate_contract(self):
        """The point of the registry: a name becomes a callable generate(prompt, temperature)."""
        for name in {p.name for p in P._PROVIDERS.values()}:
            fn = P.get_generator(name)
            assert callable(fn), f"{name} does not resolve to a generator"

    def test_no_provider_ships_a_key(self):
        """A registration names a variable; it never carries a secret."""
        for provider in P._PROVIDERS.values():
            key = provider.env_key
            assert key == "" or key.isupper() or "_" in key, f"{provider.name}: {key!r}"
            assert len(key) < 64, f"{provider.name}'s env_key looks like a value, not a name"


class TestTheRegistryIsListable:
    def test_registry_json_covers_every_provider(self):
        rows = P.registry_json()
        assert {r["name"] for r in rows} == {p.name for p in P._PROVIDERS.values()}

    def test_each_row_carries_what_a_picker_needs(self):
        for row in P.registry_json():
            for field in (
                "name",
                "tier",
                "available",
                "env_key",
                "default_model",
                "aliases",
                "needs",
            ):
                assert field in row, f"{row.get('name')} is missing {field}"

    def test_an_unavailable_provider_says_what_to_set(self):
        """ "Unavailable" with no remedy is the same unhelpful shape as a bare logged_in: false."""
        for row in P.registry_json():
            if not row["available"]:
                assert row["needs"], f"{row['name']} is unavailable and does not say why"

    def test_an_available_provider_needs_nothing(self):
        for row in P.registry_json():
            if row["available"]:
                assert row["needs"] == ""

    def test_availability_matches_the_registry(self):
        avail = P.available()
        for row in P.registry_json():
            assert row["available"] == avail[row["name"]]

    def test_the_json_cli_is_what_the_ide_calls(self):
        """list_ai_providers shells this exact command; a broken --json is an empty picker."""
        result = subprocess.run(
            [sys.executable, str(_ROOT / "scripts" / "determinex_providers.py"), "--json"],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            env={**__import__("os").environ, "PYTHONPATH": str(_ROOT / "scripts")},
        )
        assert result.returncode == 0, result.stderr[-500:]
        rows = json.loads(result.stdout.strip().splitlines()[-1])
        assert isinstance(rows, list) and rows
        assert {r["name"] for r in rows} >= set(EXPECTED), "the CLI omits providers the module has"

    def test_the_human_report_still_works(self):
        """--json is additive; the report predates it and is what a terminal user runs."""
        result = subprocess.run(
            [sys.executable, str(_ROOT / "scripts" / "determinex_providers.py")],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            env={**__import__("os").environ, "PYTHONPATH": str(_ROOT / "scripts")},
        )
        assert result.returncode == 0
        assert "provider(s) ready here" in result.stdout


class TestAgentsReportTheirOwnCapability:
    """The UI had these as hardcoded name lists; they belong to the registry."""

    def test_the_agent_list_says_who_takes_a_model(self):
        import determinex_agents as A

        rows = {r["name"]: r for r in A._agents_json()}
        for name in ("claude-code", "codex", "gemini-cli", "local-ollama", "aider"):
            assert rows[name]["supports_model"] is True, (
                f"{name} takes a model flag; reporting otherwise means the panel offers no picker "
                f"and every turn silently runs on a default"
            )

    def test_aider_is_model_assignable(self):
        """aider --help documents `--model MODEL`; it had no model_flag, so it was unassignable."""
        import determinex_agents as A

        assert A._AGENTS["aider"].model_flag == "--model"

    def test_chat_mode_capability_is_declared_not_guessed(self):
        import determinex_agents as A

        rows = {r["name"]: r for r in A._agents_json()}
        assert rows["local-ollama"]["supports_chat_mode"] is True
        # The cloud CLIs converse by default and declare no chat flag; that must read as False
        # rather than as "unknown".
        assert rows["claude-code"]["supports_chat_mode"] is False


class TestEveryOfferedRouteResolves:
    """The IDE's role picker and litellm_config.yaml are two hand-kept lists of the same thing.

    Found 2026-07-31 by diffing them: `cloud/kimi-k2` and `determinex/planner` were offered in the
    picker with no alias in the config. Selecting either produced a model string litellm cannot
    route, and `determinex/` is not a provider it knows -- so the failure lands at call time, not at
    selection, which is the worst place for it. Both were fixed; this keeps them fixed.

    The first attempt at this diff was itself a false positive worth recording: a regex matching
    everything after ``model_name:`` captured the trailing ``# comment`` on each line, so 13 of 21
    routes looked broken -- including ``determinex/engineer``, which the hive calls constantly.
    Stripping comments showed the real number was 2. A presence check that has never been
    sanity-checked against a known-good case can report anything.
    """

    @staticmethod
    def _aliases() -> set[str]:
        import yaml

        cfg = yaml.safe_load((_ROOT / "litellm_config.yaml").read_text(encoding="utf-8"))
        return {e["model_name"] for e in cfg["model_list"]}

    @staticmethod
    def _ui_routes() -> set[str]:
        import re

        src = (_ROOT / "frontend" / "src" / "lib" / "aiRouting.ts").read_text(encoding="utf-8")
        # "auto" is the router's own let-it-decide option, not a model alias.
        return set(re.findall(r'id:\s*"([^"]+)"', src)) - {"auto"}

    def test_the_config_parses(self):
        assert len(self._aliases()) > 20, "the alias map looks truncated"

    def test_the_picker_offers_something(self):
        assert len(self._ui_routes()) > 10, "the route list looks truncated; the diff below is moot"

    def test_every_offered_route_has_an_alias(self):
        missing = sorted(self._ui_routes() - self._aliases())
        assert not missing, (
            "these routes are selectable in the IDE and have no alias in litellm_config.yaml, so "
            f"choosing one fails at call time rather than at selection: {missing}"
        )

    def test_the_sanity_check_the_first_regex_failed(self):
        """A known-good alias the hive uses constantly. If the parse is broken, this catches it
        before the diff above reports every route as missing."""
        assert "determinex/engineer" in self._aliases()

    def test_kimi_is_routable(self):
        """Named directly by Ryan, and it was the broken one."""
        aliases = self._aliases()
        assert "cloud/kimi-k2" in aliases
        assert "cloud/kimi-k2" in self._ui_routes(), "routable but not offered is the other half"

    def test_planner_points_at_qwen7b_not_sentinel(self):
        """Standing rule: the architect/oracle role is qwen7b and never sentinel."""
        import yaml

        cfg = yaml.safe_load((_ROOT / "litellm_config.yaml").read_text(encoding="utf-8"))
        planner = next(e for e in cfg["model_list"] if e["model_name"] == "determinex/planner")
        model = planner["litellm_params"]["model"]
        assert "qwen2.5-coder:7b" in model, f"planner routes to {model!r}"
        assert "sentinel" not in model

    def test_a_registered_provider_with_a_key_env_is_reachable_by_alias(self):
        """The providers added to the registry must be assignable to a role, not just nameable in
        Python -- an alias here is what makes a provider a choice in the IDE."""
        aliases = self._aliases()
        for fragment in (
            "kimi",
            "grok",
            "vertex",
            "codestral",
            "together",
            "cerebras",
            "fireworks",
            "hf-",
        ):
            assert any(fragment in a for a in aliases), (
                f"no alias mentions {fragment!r}, so that provider cannot be assigned to a role"
            )
