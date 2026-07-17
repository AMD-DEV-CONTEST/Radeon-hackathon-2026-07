package model

import "testing"

func TestVocabularyEncodeDecodeRoundTrip(t *testing.T) {
	v := BuildVocabulary([]string{"AMD makes GPUs and CPUs", "GPUs are used for AI"})

	ids := v.Encode("AMD makes GPUs")
	if len(ids) != 3 {
		t.Fatalf("expected 3 real tokens, got %d", len(ids))
	}

	decoded := v.Decode(ids)
	want := "amd makes gpus"
	if decoded != want {
		t.Errorf("expected decoded text %q, got %q", want, decoded)
	}

	t.Logf("Encoded: %v, Decoded: %q", ids, decoded)
}

func TestVocabularyHandlesUnknownWords(t *testing.T) {
	v := BuildVocabulary([]string{"AMD makes GPUs"})

	ids := v.Encode("AMD makes something totally unfamiliar")
	unkID := v.WordToID["<unk>"]

	// Real, structural check: genuinely unknown words should map to
	// the real <unk> token, not fail or crash.
	foundUnk := false
	for _, id := range ids {
		if id == unkID {
			foundUnk = true
			break
		}
	}
	if !foundUnk {
		t.Error("expected at least one genuinely unknown word to map to <unk>")
	}

	t.Logf("Vocab size: %d, encoded unfamiliar text: %v", v.Size(), ids)
}
