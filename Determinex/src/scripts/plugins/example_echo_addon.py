"""Example Determinex addon: registers a trivial 'echo' provider + an oracle hint.
Shows the extension contract -- drop a file like this to host your own AI/tool."""


def register(api):
    # an AI provider addon (here a stub; real ones wrap an SDK/CLI)
    api.register_provider(
        "echo",
        tier=1,
        env_key="",
        default_model="echo/v0",
        factory=lambda model: lambda prompt, temperature: "echo: " + prompt[:40],
    )
    # a language oracle addon
    api.register_oracle_hint("elixir", "mix test")
