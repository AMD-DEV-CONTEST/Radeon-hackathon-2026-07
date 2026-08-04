import torch
import numpy as np
import torchaudio

# Reference: https://huggingface.co/facebook/wav2vec2-base-960h/blob/main/vocab.json
def char_to_token(vocab, word_delim: str, unk_id: str, c: str) -> int:
    c = c.upper()
    if c == ' ':
        c = word_delim
    return vocab.get(c, unk_id)

# For lipsync of VRoid characters.
def char_to_viseme(c: str) -> str:
    c = c.lower()
    mapping = {
        'a': 'aa', 'e': 'ee', 'i': 'ih', 'o': 'oh', 'u': 'ou',
        
        'p': 'pp', 'b': 'pp', 'm': 'pp',
    }
    return mapping.get(c, None)

# wav2vec2 has 20ms frames, and is trained on 16kHz
SAMPLE_RATE = 16000.0
FRAME_DURATION = 320.0 / SAMPLE_RATE


@torch.no_grad()
def forced_align(model, processor, audio_array: np.ndarray, sample_rate: int, transcript: str):
    # Prepare audio for PyTorch model (Needs 16kHz)
    audio_tensor = torch.tensor(audio_array, dtype=torch.float32).unsqueeze(0).to("cuda:0", dtype=torch.float16)
    if sample_rate != int(SAMPLE_RATE):
        audio_16k = torchaudio.functional.resample(audio_tensor, sample_rate, SAMPLE_RATE)
    else:
        audio_16k = audio_tensor

    # Get Logits
    input_values = processor(
        audio_16k.squeeze().cpu().numpy(), 
        return_tensors="pt", 
        sampling_rate=SAMPLE_RATE
    ).input_values.to("cuda:0")
    
    logits_tensor = model(input_values).logits
    logits = logits_tensor[0].cpu().numpy()  # Shape: [time_steps, vocab_size]
    time_steps, vocab_size = logits.shape

    # Get tokenizer vocab
    vocab = processor.tokenizer.get_vocab()
    unk_id = processor.tokenizer.unk_token_id
    word_delim = processor.tokenizer.word_delimiter_token

    # DP VITERBI
    tokens = [char_to_token(vocab, word_delim, unk_id, c) for c in transcript]
    seq = [0]
    for t in tokens:
        seq.append(t)
        seq.append(0)
    s_len = len(seq)

    neg_inf = float('-inf')
    dp = np.full((time_steps, s_len), neg_inf, dtype=np.float32)
    bt = np.zeros((time_steps, s_len), dtype=np.int32)

    dp[0, 0] = logits[0, seq[0]]
    if s_len > 1:
        dp[0, 1] = logits[0, seq[1]]

    for t in range(1, time_steps):
        for s in range(s_len):
            best_score = neg_inf
            best_prev = s

            # Handle all three legal cases
            if dp[t - 1, s] > best_score:
                best_score = dp[t - 1, s]
                best_prev = s

            if s >= 1 and dp[t - 1, s - 1] > best_score:
                best_score = dp[t - 1, s - 1]
                best_prev = s - 1

            if s >= 2 and seq[s - 1] == 0 and seq[s] != seq[s - 2] and dp[t - 1, s - 2] > best_score:
                best_score = dp[t - 1, s - 2]
                best_prev = s - 2

            dp[t, s] = best_score + logits[t, seq[s]]
            bt[t, s] = best_prev

    path = np.zeros(time_steps, dtype=np.int32)
    if dp[time_steps - 1, s_len - 1] > dp[time_steps - 1, s_len - 2]:
        path[time_steps - 1] = s_len - 1
    else:
        path[time_steps - 1] = s_len - 2

    for t in range(time_steps - 2, -1, -1):
        path[t] = bt[t + 1, path[t + 1]]

    token_spans = []
    t = 0
    while t < time_steps:
        s = path[t]
        if seq[s] != 0:
            start_frame = t
            while t < time_steps and path[t] == s:
                t += 1
            ch = transcript[s // 2]
            token_spans.append((start_frame, t, ch))
        else:
            t += 1

    alignments = []
    visemes = []
    current_word = ""
    word_start = 0.0
    word_end = 0.0

    for start_frame, end_frame, ch in token_spans:
        start_sec = round(start_frame * FRAME_DURATION, 3)
        end_sec = round(end_frame * FRAME_DURATION, 3)

        viseme = char_to_viseme(ch)
        if viseme:
            visemes.append({"viseme": viseme, "start": start_sec})

        if ch == ' ':
            if current_word:
                alignments.append({"word": current_word, "start": word_start, "end": word_end})
                current_word = ""
        else:
            if not current_word:
                word_start = start_sec
            current_word += ch
            word_end = end_sec

    if current_word:
        alignments.append({"word": current_word, "start": word_start, "end": word_end})

    return {"words": alignments, "visemes": visemes}
