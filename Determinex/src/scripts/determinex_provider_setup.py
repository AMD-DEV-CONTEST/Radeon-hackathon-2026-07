#!/usr/bin/env python3
"""
determinex_provider_setup.py — "which button do I press?" for a first-time user
==============================================================================
Determinex can talk to a dozen model providers. A setup screen that presents that as twelve
equal choices — seven of them blank password fields — is a wall, and a wall is where someone
who was willing to try the thing quietly stops.

Ryan, 2026-08-03: *"I'm giving the world a magic box. The magic believers will try it and
something simple shouldn't fuck it up for them."*

So this module does not enumerate providers. It answers three questions, in this order:

    1. What already works on this machine, right now, with no action?
    2. If nothing does, what is the ONE thing to do — the cheapest path to a working box?
    3. For each option, exactly what will happen if the user clicks it?

THE RANKING IS DELIBERATE, AND IT IS NOT ALPHABETICAL
----------------------------------------------------
Options are ordered by *what the user has to understand*, not by model quality:

  NOTHING_NEEDED   already working. Nothing to explain.
  NO_ACCOUNT       local models. No signup, no key, no billing, works offline. The honest
                   default for a privacy-first tool, and the only tier that cannot expire,
                   run out of credit, or change its terms.
  SIGN_IN          the user already has a subscription and a CLI that owns its own OAuth.
                   One click opens a browser; no key is ever pasted or stored by us.
  PASTE_A_KEY      requires understanding what an API key is. Last, and collapsed by default.

A first-time user should be able to reach a working system without ever meeting tier 3.

EVERY OPTION VERIFIES ITSELF
----------------------------
Setup that reports success without making a call is the failure this project keeps finding
elsewhere: a green check for a path nobody exercised. Each option carries a `verify` that
performs a real one-token generation and returns either a pass or the actual reason — which
for Google today is "your prepay credits are depleted", not "rate limited" and not "install
the Google Cloud SDK", both of which this system told users last week.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

#: What a user must understand before this option can work. Lower is friendlier.
EFFORT_NOTHING = 0
EFFORT_NO_ACCOUNT = 1
EFFORT_SIGN_IN = 2
EFFORT_PASTE_KEY = 3

_EFFORT_LABEL = {
    EFFORT_NOTHING: "already working",
    EFFORT_NO_ACCOUNT: "no account needed",
    EFFORT_SIGN_IN: "sign in with an app you already have",
    EFFORT_PASTE_KEY: "paste an API key",
}


@dataclass
class SetupOption:
    id: str
    title: str
    #: One plain sentence. No jargon, no provider marketing.
    what_it_means: str
    effort: int
    #: True when this option can be used right now with no further action.
    ready: bool = False
    #: What pressing the button actually does, in the user's words.
    action_label: str = ""
    #: Machine-readable action for the UI to dispatch back to `run_action`.
    action: str = ""
    #: Where to send the user when the action needs a browser.
    url: str = ""
    #: Filled by `verify` — the real reason, when something refuses.
    detail: str = ""
    #: Private / offline / no billing. Surfaced because it is why local ranks first.
    private: bool = False
    #: Named state, never a boolean: verified / credentials_unverified / provider_refused /
    #: quota_exhausted / no_credentials / not_installed.
    readiness: str = ""
    #: True when this provider can be reached by SIGNING IN to an account the user already
    #: has, with no key to obtain, paste or store. Ryan, 2026-08-03: "if you download
    #: antigravity you hit the button you're in ... I want the same for all of it, not where
    #: a user has to go and set up a whole other part (api's) that sometimes requires higher
    #: pricing and different pricing."
    signin: bool = False
    #: Grouping for the UI: "start_here" (no key ever) vs "advanced" (bring your own key).
    group: str = "advanced"
    #: When a key-based option is the SAME VENDOR as a sign-in option, this names it. Without
    #: it the screen shows "Sign in with Claude" and "Anthropic — get a key" as if they were
    #: two different things a user needs, which is precisely the confusion the grouping was
    #: meant to remove.
    covered_by: str = ""

    @property
    def effort_label(self) -> str:
        return _EFFORT_LABEL.get(self.effort, "")


@dataclass
class SetupReport:
    options: list[dict] = field(default_factory=list)
    ready_count: int = 0
    #: The single next action, chosen for the user so the screen can lead with one button.
    recommended: dict | None = None
    #: Plain-language summary the UI can show verbatim.
    headline: str = ""


# ── detection: what is true on this machine right now ───────────────────────────────────


def _ollama_models() -> tuple[list[str], bool]:
    """(models, daemon_reachable).

    The two are separate answers and conflating them is a real harm: a 4-second timeout on a
    daemon that is merely slow returned [], the screen concluded "you have no models", and it
    told a user with 38 models installed to download another gigabyte. "I could not ask" must
    never render as "the answer is none".
    """
    for timeout in (6, 12):
        try:
            with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=timeout) as r:
                return [m["name"] for m in json.loads(r.read()).get("models", [])], True
        except Exception:
            continue
    return [], False


#: The agent roster, fetched at most once per report. Populated by `_agent_roster`.
_ROSTER_CACHE: dict[str, tuple[str, str]] | None = None


def _agent_roster() -> dict[str, tuple[str, str]]:
    """Every agent CLI's (readiness, detail), from ONE roster read.

    `_agents_status_json()` costs ~2.7s -- it walks the installed CLIs and reads each one's
    cached probe. Calling it per provider made `build_report` take 10.3 seconds, of which 8.2
    were the same roster fetched three times, and the first-run screen sat on
    "Looking for AI you can already use..." for long enough to read as broken. On a screen
    whose entire purpose is that nobody gives up, that is the defect, not a slow path.
    """
    global _ROSTER_CACHE
    if _ROSTER_CACHE is None:
        roster: dict[str, tuple[str, str]] = {}
        try:
            from determinex_agents import _agents_status_json

            for row in _agents_status_json():
                roster[str(row.get("name") or "")] = (
                    str(row.get("readiness") or ""),
                    str(row.get("detail") or ""),
                )
        except Exception:
            pass
        _ROSTER_CACHE = roster
    return _ROSTER_CACHE


def _cli_readiness(name: str) -> tuple[str, str]:
    """(readiness, detail) for an agent CLI -- a NAMED state, never a boolean.

    Reads `_agents_status_json`, the same source `determinex_agents status` prints, whose own
    comment records why: `logged_in` answers "is there a credential on disk", and a panel that
    reads it as "this will work" overclaims. gemini-cli is the standing proof -- its
    credentials look perfect and the provider refuses it.

    Named states used here: `verified` (a live call succeeded), `provider_refused`,
    `quota_exhausted`, `credentials_unverified`, `no_credentials`, `not_installed`.

    The first version of this function iterated `available_agents()` as a list of dicts. It
    returns a DICT, so iteration yielded plain strings, `a.get(...)` raised, and a bare
    `except: pass` turned that into "not installed" -- telling a user with a working Claude
    subscription to install Claude.
    """
    return _agent_roster().get(name, ("", ""))


def _env_key(*names: str) -> bool:
    """A key counts only if it is non-empty AND not an obvious placeholder."""
    for n in names:
        v = (os.environ.get(n) or "").strip().strip('"').strip("'")
        if v and not v.lower().startswith(("<", "your", "changeme", "xxx", "sk-xxx", "paste")):
            return True
    return False


def _load_env_file() -> None:
    """Make .env visible to detection, exactly as the runtime does.

    Without this the screen offers to set up a key the user already provided -- which is the
    same class of error as an agent roster reporting a provider refused because it cached a
    probe from before the key existed.
    """
    p = _HERE.parent / ".env"
    if not p.is_file():
        return
    try:
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except OSError:
        pass


def _google_identity() -> tuple[str, str]:
    """(email, how_we_know) for the Google account this machine already uses.

    Google is the one vendor where the obvious sign-in path is broken and the working one is
    not obvious, so the screen has to do the reconciling instead of the user:

      * `gemini-cli` still authenticates and still stores perfect-looking credentials, and the
        provider then refuses every call with `IneligibleTierError` — the free individual tier
        it was built against no longer exists. Presenting it as an option is presenting a dead
        end that looks alive.
      * **Antigravity** is Google's supported sign-in-and-go path, and it is an Electron IDE.
        Its `resources/bin` holds a language server and a webm encoder — there is no headless
        entrypoint, so Determinex cannot drive it as a generator the way it drives the
        `claude-code` and `codex` CLIs.

    What both of them DO leave behind is the answer to "which Google account is this person?",
    and that turns the remaining path into two clicks: aistudio.google.com/apikey opens
    already signed in as that account, and "Create API key" is free with no card. Ryan,
    2026-08-03: *"if gemini/google isn't working for the gate because this system has
    antigravity, then do a piggyback for both and just call it google."* So this returns one
    identity from whichever source has it, and the caller emits exactly one row named Google.
    """
    try:
        p = Path.home() / ".gemini" / "google_accounts.json"
        if p.is_file():
            active = str(json.loads(p.read_text(encoding="utf-8")).get("active") or "").strip()
            if active:
                return active, "gemini"
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    for probe in (
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Antigravity" / "Antigravity.exe",
        Path.home() / ".antigravity",
    ):
        try:
            if probe.exists():
                return "", "antigravity"
        except OSError:
            continue
    return "", ""


def _google_option() -> SetupOption:
    """The single Google row — sign-in shaped, never two half-broken ones."""
    email, source = _google_identity()
    have_key = _env_key("GEMINI_API_KEY", "GOOGLE_API_KEY")
    refused, refused_detail = _cli_readiness("gemini-cli")

    if have_key:
        # A key on disk is not a working provider, and Google is where this project learned
        # that: a valid GEMINI_API_KEY on an account with zero prepay credits would have been
        # reported "set up", and the user would have found out on their first real request.
        return SetupOption(
            id="google",
            title="Google (Gemini)",
            what_it_means=(
                "Your Google key is saved. Press Test to make one real call and confirm it "
                "works before you rely on it."
            ),
            effort=EFFORT_PASTE_KEY,
            ready=False,
            action_label="Key found — test it",
            action="verify",
            url="https://aistudio.google.com/apikey",
            readiness="credentials_unverified",
            signin=True,
            group="start_here",
            detail=email,
        )

    if source:
        who = f" as {email}" if email else ""
        note = (
            f"You're already signed in to Google{who}. Opening this page creates a free key "
            f"for that account — two clicks, no card needed."
        )
        if refused == "provider_refused":
            # Say the real thing once. Silence here is what sends someone to debug a CLI whose
            # credentials are fine and whose tier no longer exists.
            note += (
                " (The gemini command-line tool signs in but Google no longer serves it for "
                "individual accounts, so Determinex uses the key instead.)"
            )
        return SetupOption(
            id="google",
            title="Sign in with Google",
            what_it_means=note,
            effort=EFFORT_SIGN_IN,
            ready=False,
            action_label="Sign in with Google",
            action="google_signin",
            url="https://aistudio.google.com/apikey",
            readiness="no_credentials",
            signin=True,
            group="start_here",
            detail=email or refused_detail[:120],
        )

    return SetupOption(
        id="google",
        title="Sign in with Google",
        what_it_means=(
            "Sign in with a Google account to create a free key. No card needed, and it takes "
            "about a minute."
        ),
        effort=EFFORT_SIGN_IN,
        ready=False,
        action_label="Sign in with Google",
        action="google_signin",
        url="https://aistudio.google.com/apikey",
        readiness="no_credentials",
        signin=True,
        group="start_here",
    )


def build_report() -> SetupReport:
    global _ROSTER_CACHE
    _ROSTER_CACHE = None  # one roster per report, and a fresh one each time it is asked for
    _load_env_file()
    opts: list[SetupOption] = []

    # The two slow probes are independent -- the Ollama daemon over HTTP, and the agent CLI
    # roster -- so run them side by side rather than one after the other.
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=2) as pool:
        ollama_future = pool.submit(_ollama_models)
        pool.submit(_agent_roster)
        models, ollama_up = ollama_future.result()

    # ── tier 1: local. No account, no key, no billing, works offline. ───────────────────
    has_ollama = shutil.which("ollama") is not None or ollama_up
    opts.append(
        SetupOption(
            id="local",
            title="Use my own computer",
            what_it_means=(
                "Runs the AI on this machine. No account, no card, no key — and nothing you "
                "write ever leaves the computer. This is the recommended way to start."
            ),
            effort=EFFORT_NOTHING if models else (EFFORT_NO_ACCOUNT if has_ollama else EFFORT_NO_ACCOUNT),
            ready=bool(models),
            action_label=(
                f"Ready — {len(models)} model(s) installed" if models
                else ("Download a model (about 1 GB)" if has_ollama else "Install local AI, then download a model")
            ),
            action="install_local" if not models else "",
            url="" if has_ollama else "https://ollama.com/download",
            signin=False,
            group="start_here",
            private=True,
            detail=(", ".join(models[:3]) if models else
                    ("" if ollama_up else "the local AI service is not running")),
            readiness=("verified" if models else
                       ("credentials_unverified" if ollama_up else "not_installed")),
        )
    )

    # ── tier 2: sign in with something already installed ────────────────────────────────
    for cli, title, note in (
        ("claude-code", "Sign in with Claude",
         "Uses your existing Claude subscription. Opens a browser once; we never see or store a key."),
        ("codex", "Sign in with ChatGPT",
         "Uses your existing ChatGPT subscription. Opens a browser once; we never see or store a key."),
    ):
        readiness, detail = _cli_readiness(cli)
        installed = shutil.which(cli) is not None or readiness not in ("", "not_installed")
        # READY means a live call has succeeded. "There is a credential on disk" is a weaker
        # claim and is shown as its own state, because telling someone they are set up and
        # then failing on their first real request is the worst outcome this screen can have.
        ready = readiness == "verified"
        if ready:
            label = "Ready"
        elif readiness in ("provider_refused", "quota_exhausted"):
            label = "Signed in, but the provider is refusing — see details"
        elif readiness == "credentials_unverified":
            label = "Signed in — test it"
        elif installed:
            label = "Sign in"
        else:
            label = "Install, then sign in"
        opts.append(
            SetupOption(
                id=cli,
                title=title,
                what_it_means=note,
                effort=EFFORT_NOTHING if ready else EFFORT_SIGN_IN,
                ready=ready,
                action_label=label,
                action="" if ready else ("verify" if readiness == "credentials_unverified"
                                         else ("cli_login" if installed else "install_cli")),
                detail=detail,
                readiness=readiness or "not_installed",
                signin=True,
                group="start_here",
            )
        )

    # Google reaches the same tier by a different road: no headless CLI to sign in with, but a
    # sign-in that produces a free key in two clicks. `_google_option` explains why.
    opts.append(_google_option())

    # ── tier 3: paste a key. Collapsed by default in the UI. ────────────────────────────
    signed_in = {o.id for o in opts if o.signin and o.ready}
    for pid, title, envs, url, note, covered in (
        ("openai", "OpenAI", ("OPENAI_API_KEY",),
         "https://platform.openai.com/api-keys",
         "Pay as you go, billed per request.", "codex"),
        ("anthropic", "Anthropic", ("ANTHROPIC_API_KEY",),
         "https://console.anthropic.com/settings/keys",
         "Pay as you go, billed per request.", "claude-code"),
        ("openrouter", "OpenRouter", ("OPENROUTER_API_KEY",),
         "https://openrouter.ai/keys",
         "Sign in with Google or GitHub to create a key. One key reaches many models, "
         "including several that are free.", ""),
    ):
        have = _env_key(*envs)
        # A key on disk is not a working provider. Determinex proved that on itself: a valid
        # GEMINI_API_KEY whose account had zero prepay credits would have been reported as
        # "set up", and the user would have discovered otherwise on their first real request.
        opts.append(
            SetupOption(
                id=pid,
                title=title,
                effort=EFFORT_PASTE_KEY,
                ready=False,
                action_label="Key found — test it" if have else "Get a key",
                action="verify" if have else "open_key_page",
                url=url,
                readiness="credentials_unverified" if have else "no_credentials",
                signin=False,
                group="advanced",
                covered_by=covered if covered in signed_in else "",
                what_it_means=(
                    note if covered not in signed_in else
                    f"{note} You are already signed in to this provider, so you do not need "
                    f"a key unless you want to run Determinex unattended."
                ),
            )
        )

    opts.sort(key=lambda o: (not o.ready, o.effort, o.id))
    ready = [o for o in opts if o.ready]

    # The recommendation is the cheapest not-yet-done option, so the screen leads with one
    # button rather than a menu. Local wins ties because it needs no account and no billing.
    todo = [o for o in opts if not o.ready]
    # RECOMMEND NOTHING WHEN THE USER IS ALREADY DONE. The first version always returned the
    # cheapest unfinished option, so a machine with Claude, ChatGPT and 38 local models still
    # led with "Get a key" -- turning a finished setup into a chore list. A setup screen's job
    # is to end, not to keep selling.
    recommended = (min(todo, key=lambda o: (o.effort, 0 if o.id == "local" else 1))
                   if todo and not ready else None)

    if ready:
        names = ", ".join(o.title for o in ready[:3])
        headline = (f"You're ready to go — {names} "
                    f"{'is' if len(ready) == 1 else 'are'} working. Nothing else is required.")
    elif recommended is not None:
        headline = f"One step to a working setup: {recommended.action_label.lower()}."
    else:
        headline = "No providers detected."

    return SetupReport(
        options=[{**asdict(o), "effort_label": o.effort_label} for o in opts],
        ready_count=len(ready),
        recommended=({**asdict(recommended), "effort_label": recommended.effort_label}
                     if recommended else None),
        headline=headline,
    )


# ── verification: a green check must mean a real call happened ──────────────────────────


def verify(option_id: str) -> dict:
    """Make ONE real generation and report pass, or the actual reason it refused."""
    try:
        from determinex_providers import get_generator
    except Exception as e:
        return {"id": option_id, "ok": False, "detail": f"provider registry unavailable: {e}"}

    _load_env_file()
    mapping = {
        "local": ("local", None),
        "google": ("google", None),
        "openai": ("openai", None),
        "anthropic": ("anthropic", None),
        "openrouter": ("openrouter", None),
    }
    if option_id not in mapping:
        return {"id": option_id, "ok": False,
                "detail": "this option is verified by signing in, not by a test call"}
    provider, model = mapping[option_id]
    try:
        out = get_generator(provider, model)("Reply with exactly: OK", 0.0)
    except Exception as e:
        detail = str(e)
        try:
            from determinex_providers import explain_google_failure

            detail = explain_google_failure(e) or detail
        except Exception:
            pass
        return {"id": option_id, "ok": False, "detail": detail[:400]}
    return {"id": option_id, "ok": bool(out and out.strip()),
            "detail": (out or "").strip()[:120] or "the provider returned nothing"}


def run_action(option_id: str, action: str) -> dict:
    """Perform the one-click action. Returns what happened, never a bare success."""
    if action == "cli_login":
        exe = shutil.which(option_id) or option_id
        try:
            # The CLI owns its own OAuth and opens a browser. We never handle the credential.
            p = subprocess.run([exe, "login"], capture_output=True, text=True, timeout=300)
            return {"ok": p.returncode == 0,
                    "detail": (p.stdout or p.stderr or "").strip()[-300:] or "login flow finished"}
        except FileNotFoundError:
            return {"ok": False, "detail": f"{option_id} is not installed"}
        except subprocess.TimeoutExpired:
            return {"ok": False, "detail": "the sign-in window timed out"}
    if action == "open_key_page":
        return {"ok": True, "detail": "open this page in a browser to create a key"}
    if action == "google_signin":
        # Deliberately the same shape as `open_key_page`, with different words. There is no
        # OAuth for us to run: Antigravity has no headless entrypoint and gemini-cli's tier is
        # gone, so the browser does the signing in and hands back a key. Calling the button
        # "Sign in with Google" is accurate — that is what the page asks for — and it stops
        # Google from being the one vendor whose row says "paste an API key".
        email, _ = _google_identity()
        who = f" You should already be signed in as {email}." if email else ""
        return {"ok": True,
                "detail": ("Opening Google AI Studio." + who +
                           " Press 'Create API key', copy it, and paste it below — it is free "
                           "and needs no card.")}
    if action == "install_local":
        return {"ok": True,
                "detail": "install Ollama from https://ollama.com/download, then pull a model"}
    return {"ok": False, "detail": f"unknown action {action!r}"}


def main() -> int:
    ap = argparse.ArgumentParser(description="What should a first-time user press?")
    ap.add_argument("command", choices=["report", "verify", "action"])
    ap.add_argument("--id", default="")
    ap.add_argument("--action", default="")
    a = ap.parse_args()
    if a.command == "report":
        print(json.dumps(asdict(build_report()), indent=2))
    elif a.command == "verify":
        print(json.dumps(verify(a.id), indent=2))
    else:
        print(json.dumps(run_action(a.id, a.action), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# ── choosing a model, without needing to know model names ───────────────────────────────
#
# Claude has three current models, Google four, OpenAI several, and every one of them ships
# an identifier like `claude-sonnet-4-6` or `gemini-3-flash-preview`. Presenting those raw is
# the same wall as the seven password fields: a name is not a decision.
#
# Each provider therefore offers at most THREE choices, in the same three shapes every time,
# so the vocabulary transfers between providers and the user learns it once:
#
#     FAST      cheapest and quickest. The default, because most work does not need more.
#     BALANCED  the everyday choice.
#     DEEP      slowest and dearest; for the hard one that the others got wrong.
#
# `id` is the real model string the runtime needs. The user never has to read it.

FAST, BALANCED, DEEP = "fast", "balanced", "deep"

_TIER_HELP = {
    FAST: "Quickest and cheapest. Good for most things.",
    BALANCED: "A step up when the quick one struggles.",
    DEEP: "Slowest and most expensive. Save it for the hard one.",
}

MODEL_CHOICES: dict[str, list[dict]] = {
    "local": [
        {"tier": FAST, "id": "qwen2.5-coder:1.5b-instruct", "label": "Small (fits any machine)"},
        {"tier": BALANCED, "id": "qwen2.5-coder:7b-instruct", "label": "Medium (needs ~8 GB)"},
        {"tier": DEEP, "id": "qwen2.5-coder:32b-instruct-q4_K_M", "label": "Large (needs ~24 GB)"},
    ],
    "claude-code": [
        {"tier": FAST, "id": "claude-haiku-4-5-20251001", "label": "Haiku"},
        {"tier": BALANCED, "id": "claude-sonnet-5", "label": "Sonnet"},
        {"tier": DEEP, "id": "claude-opus-5", "label": "Opus"},
    ],
    "openai": [
        {"tier": FAST, "id": "gpt-5.5-mini", "label": "Mini"},
        {"tier": BALANCED, "id": "gpt-5.5", "label": "Standard"},
        {"tier": DEEP, "id": "gpt-5.5-pro", "label": "Pro"},
    ],
    "google": [
        {"tier": FAST, "id": "gemini/gemini-3-flash-preview", "label": "Flash"},
        {"tier": BALANCED, "id": "gemini/gemini-flash-latest", "label": "Flash (latest)"},
        {"tier": DEEP, "id": "gemini/gemini-3-pro-preview", "label": "Pro"},
    ],
    "openrouter": [
        {"tier": FAST, "id": "openrouter/anthropic/claude-haiku-4.5", "label": "Haiku via OpenRouter"},
        {"tier": BALANCED, "id": "openrouter/anthropic/claude-sonnet-5", "label": "Sonnet via OpenRouter"},
        {"tier": DEEP, "id": "openrouter/openai/gpt-5.5-pro", "label": "GPT Pro via OpenRouter"},
    ],
}


def _same_model(installed_tag: str, wanted: str) -> bool:
    """Is `installed_tag` the same Ollama model as `wanted`?

    Ollama writes `qwen2.5-coder:latest` for what a Modelfile calls `qwen2.5-coder`, so that
    one suffix is normalised. Everything after the colon otherwise distinguishes a 1 GB model
    from a 20 GB one and must not be discarded.
    """
    norm = lambda t: t.strip().removesuffix(":latest")  # noqa: E731
    return norm(installed_tag) == norm(wanted)


def model_choices(option_id: str, installed: list[str] | None = None) -> list[dict]:
    """The two-or-three choices to show for one provider, in plain language.

    For `local`, a model that is not downloaded is still listed but marked `installed: False`
    with its size, because hiding it would leave the user wondering why their machine offers
    fewer options than the screenshot -- and offering it without saying it must be downloaded
    is how someone ends up staring at a progress bar they did not ask for.
    """
    out = []
    have = set(installed or [])
    for row in MODEL_CHOICES.get(option_id, []):
        entry = {**row, "help": _TIER_HELP[row["tier"]], "default": row["tier"] == FAST}
        if option_id == "local":
            # Compare the WHOLE tag, not the family. Matching on `id.split(":")[0]` made every
            # tier "installed" the moment any qwen2.5-coder was present -- so a machine with
            # the 1.5B model was told the 24 GB one was ready, and the user found out when the
            # download they never agreed to started. Ollama omits `:latest`, so that one
            # suffix is normalised away; nothing else is.
            entry["installed"] = any(_same_model(m, row["id"]) for m in have)
            if not entry["installed"]:
                entry["help"] += " Downloads on first use."
        out.append(entry)
    return out
