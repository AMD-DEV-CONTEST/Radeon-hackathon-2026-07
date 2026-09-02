# HF CausalLM loss upcasts the full logits tensor — OOM on 8GB at vocab 152K

One-liner: never pass `labels=` into a Hugging Face CausalLM forward on
big-vocab models when VRAM is tight — `ForCausalLMLoss` calls
`logits.float()` on the whole [batch, seq, vocab] tensor (~2.5GB extra
at 8×450×151936) and OOMs the 4060.

Hit July 16, 2026 in the pilot slice. Fix in foundry/train.py: forward
without labels, then compute cross-entropy only over positions where
labels != -100 (our targets are ~25 tokens/example, so the upcast
shrinks from gigabytes to ~megabytes):

    logits = out.logits[:, :-1]
    labels_shift = labels[:, 1:]
    mask = labels_shift != -100
    loss = F.cross_entropy(logits[mask].float(), labels_shift[mask])

Also worth keeping on the Radeon: identical code path, and the freed
headroom is what lets batch size stay at 8 regardless of card.
