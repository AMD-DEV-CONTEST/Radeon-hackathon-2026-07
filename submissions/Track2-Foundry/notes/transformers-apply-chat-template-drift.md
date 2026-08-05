# apply_chat_template(tokenize=True) returns BatchEncoding, not a list

One-liner: don't consume `tokenizer.apply_chat_template(...)`'s tokenized
output directly — in the installed transformers (4.x, July 2026) it
returns a BatchEncoding where older code expected a plain id list, and
`+` with a list TypeErrors.

Hit July 16, 2026 in train.py. Stable pattern used instead: render with
`tokenize=False`, then tokenize explicitly —

    text = tokenizer.apply_chat_template(msgs, add_generation_prompt=True,
                                         enable_thinking=False, tokenize=False)
    ids = tokenizer(text, add_special_tokens=False)["input_ids"]

This is immune to the return-type drift and keeps prompt/target token
accounting explicit (we concatenate our own target ids after it).
