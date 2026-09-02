# Qwen3 thinking-hybrid template: train and serve must agree or content is empty

One-liner: the student is trained with `enable_thinking=False`; when the
exported GGUF is served by llama-server (--jinja), every request must
send `"chat_template_kwargs": {"enable_thinking": false}` or the model
thinks, llama-server routes the output to `reasoning_content`, and
`message.content` comes back as an empty string.

Hit July 16, 2026: the export smoke test returned '' and failed exactly
as designed. Qwen3 base checkpoints (0.6B student included) are
thinking-hybrid; the template renders a different assistant prefix per
mode, so a mode mismatch between training and serving silently breaks
output parsing rather than erroring.

Applies everywhere the student is served — eval harnesses, the agent,
the demo. The Instruct-2507 teacher is non-thinking, so teacher calls
don't need the kwarg (harmless if sent).
