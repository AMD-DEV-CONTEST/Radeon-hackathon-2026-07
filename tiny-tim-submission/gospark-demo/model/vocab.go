package model

import (
	"encoding/json"
	"fmt"
	"os"
	"strings"
)

// Vocabulary is a genuinely simple, real word-level tokenizer --
// deliberately NOT GoSpark's real, established BPE tokenizer (real,
// separate IP), a simple, honest, different approach appropriate for
// this narrow demo's own scope.
type Vocabulary struct {
	WordToID map[string]int
	IDToWord []string
}

const (
	unkToken = "<unk>"
	padToken = "<pad>"
	eosToken = "<eos>"
)

// tokenizeWords splits real text into real, simple lowercase word
// tokens -- whitespace-separated, with basic punctuation stripped.
func tokenizeWords(text string) []string {
	text = strings.ToLower(text)
	fields := strings.FieldsFunc(text, func(r rune) bool {
		if r == '\'' || r == '-' {
			return false // keep contractions and hyphenated words intact
		}
		return !((r >= 'a' && r <= 'z') || (r >= '0' && r <= '9'))
	})
	return fields
}

// BuildVocabulary builds a real vocabulary from a real corpus of
// texts -- every genuinely distinct word encountered gets a real,
// stable token ID, plus the real special tokens (<unk>, <pad>, <eos>)
// reserved at the start.
func BuildVocabulary(texts []string) *Vocabulary {
	v := &Vocabulary{
		WordToID: make(map[string]int),
		IDToWord: []string{},
	}

	for _, special := range []string{padToken, unkToken, eosToken} {
		v.addWord(special)
	}

	for _, text := range texts {
		for _, word := range tokenizeWords(text) {
			v.addWord(word)
		}
	}

	return v
}

func (v *Vocabulary) addWord(word string) {
	if _, exists := v.WordToID[word]; exists {
		return
	}
	id := len(v.IDToWord)
	v.WordToID[word] = id
	v.IDToWord = append(v.IDToWord, word)
}

// Size returns the real, current vocabulary size.
func (v *Vocabulary) Size() int {
	return len(v.IDToWord)
}

// Encode converts real text into real token IDs, mapping any
// genuinely unknown word to the real <unk> token rather than failing.
func (v *Vocabulary) Encode(text string) []int {
	words := tokenizeWords(text)
	ids := make([]int, len(words))
	unkID := v.WordToID[unkToken]
	for i, w := range words {
		if id, ok := v.WordToID[w]; ok {
			ids[i] = id
		} else {
			ids[i] = unkID
		}
	}
	return ids
}

// Decode converts real token IDs back into real, readable text.
func (v *Vocabulary) Decode(ids []int) string {
	words := make([]string, 0, len(ids))
	for _, id := range ids {
		if id >= 0 && id < len(v.IDToWord) {
			words = append(words, v.IDToWord[id])
		} else {
			words = append(words, unkToken)
		}
	}
	return strings.Join(words, " ")
}

// SaveVocabulary writes the real, current vocabulary to a real file
// on disk -- needed so a later chat/inference session can load the
// exact same real word-to-ID mapping the model was actually trained
// with.
func SaveVocabulary(v *Vocabulary, path string) error {
	data, err := json.Marshal(v.IDToWord)
	if err != nil {
		return fmt.Errorf("save vocabulary: marshaling: %w", err)
	}
	if err := os.WriteFile(path, data, 0644); err != nil {
		return fmt.Errorf("save vocabulary: writing %q: %w", path, err)
	}
	return nil
}

// LoadVocabulary reads a real vocabulary file and reconstructs the
// real, complete Vocabulary from it.
func LoadVocabulary(path string) (*Vocabulary, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("load vocabulary: reading %q: %w", path, err)
	}

	var idToWord []string
	if err := json.Unmarshal(data, &idToWord); err != nil {
		return nil, fmt.Errorf("load vocabulary: unmarshaling %q: %w", path, err)
	}

	v := &Vocabulary{
		WordToID: make(map[string]int, len(idToWord)),
		IDToWord: idToWord,
	}
	for id, word := range idToWord {
		v.WordToID[word] = id
	}

	return v, nil
}
