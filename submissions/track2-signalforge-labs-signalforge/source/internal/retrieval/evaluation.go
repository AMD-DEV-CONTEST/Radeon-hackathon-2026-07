package retrieval

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"sort"
	"time"
)

const EvalSchemaV1 = "signalforge/retrieval-eval/v1"

type EvalSource struct {
	DocumentID      string     `json:"document_id"`
	CompanyID       string     `json:"company_id"`
	EvidenceType    string     `json:"evidence_type"`
	FilingID        string     `json:"filing_id,omitempty"`
	AccessionNumber string     `json:"accession_number,omitempty"`
	FormType        string     `json:"form_type,omitempty"`
	DocumentType    string     `json:"document_type"`
	AuthorityTier   string     `json:"authority_tier"`
	Issuer          string     `json:"issuer"`
	Language        string     `json:"language"`
	RightsClass     string     `json:"rights_class"`
	Audited         bool       `json:"audited"`
	FiledWithSEC    bool       `json:"filed_with_sec"`
	ForwardLooking  bool       `json:"forward_looking"`
	Promotional     bool       `json:"promotional"`
	PublishedAt     time.Time  `json:"published_at"`
	EffectiveAt     *time.Time `json:"effective_at,omitempty"`
	SupersededAt    *time.Time `json:"superseded_at,omitempty"`
	SourceURI       string     `json:"source_uri"`
	DocumentSHA256  string     `json:"document_sha256"`
	AvailableAt     time.Time  `json:"available_at"`
	RetrievedAt     time.Time  `json:"retrieved_at"`
}

type EvalChunk struct {
	ChunkID    string   `json:"chunk_id"`
	DocumentID string   `json:"document_id"`
	Section    string   `json:"section"`
	Page       int      `json:"page,omitempty"`
	Locator    string   `json:"locator"`
	Periods    []string `json:"periods,omitempty"`
	ClaimKey   string   `json:"claim_key,omitempty"`
	ClaimValue string   `json:"claim_value,omitempty"`
	Text       string   `json:"text"`
}

type EvalQuestion struct {
	QuestionID       string   `json:"question_id"`
	Text             string   `json:"text"`
	CompanyIDs       []string `json:"company_ids,omitempty"`
	TopK             int      `json:"top_k"`
	RelevantChunkIDs []string `json:"relevant_chunk_ids"`
}

type EvalSet struct {
	SchemaVersion string         `json:"schema_version"`
	AsOf          time.Time      `json:"as_of"`
	Description   string         `json:"description"`
	Sources       []EvalSource   `json:"sources"`
	Chunks        []EvalChunk    `json:"chunks"`
	Questions     []EvalQuestion `json:"questions"`
}

type EvalMetrics struct {
	QuestionCount        int     `json:"question_count"`
	RecallAtK            float64 `json:"recall_at_k"`
	PrecisionAtK         float64 `json:"precision_at_k"`
	CompleteEvidenceRate float64 `json:"complete_evidence_rate"`
	CitationCorrectness  float64 `json:"citation_correctness"`
	MeanContextTokens    float64 `json:"mean_context_tokens"`
}

func LoadEvalSet(path string) (EvalSet, []Chunk, error) {
	payload, err := os.ReadFile(path)
	if err != nil {
		return EvalSet{}, nil, err
	}
	var eval EvalSet
	if err := json.Unmarshal(payload, &eval); err != nil {
		return EvalSet{}, nil, err
	}
	if eval.SchemaVersion != EvalSchemaV1 || eval.AsOf.IsZero() || len(eval.Sources) == 0 || len(eval.Chunks) == 0 || len(eval.Questions) == 0 {
		return EvalSet{}, nil, errors.New("complete retrieval evaluation set is required")
	}
	sources := make(map[string]EvalSource, len(eval.Sources))
	for _, source := range eval.Sources {
		if source.DocumentID == "" || source.CompanyID == "" || source.EvidenceType == "" || source.DocumentType == "" || source.AuthorityTier == "" || source.Issuer == "" || source.Language == "" || source.RightsClass == "" || source.SourceURI == "" || !validSHA(source.DocumentSHA256) {
			return EvalSet{}, nil, errors.New("invalid retrieval evaluation source")
		}
		if source.PublishedAt.IsZero() || source.AvailableAt.Before(source.PublishedAt) || source.RetrievedAt.Before(source.AvailableAt) {
			return EvalSet{}, nil, errors.New("invalid retrieval evaluation source timestamps")
		}
		if source.EvidenceType == "regulatory_filing" && (source.FilingID == "" || source.AccessionNumber == "" || source.FormType == "") {
			return EvalSet{}, nil, errors.New("regulatory evaluation source requires filing identity")
		}
		if _, exists := sources[source.DocumentID]; exists {
			return EvalSet{}, nil, errors.New("duplicate retrieval evaluation document")
		}
		sources[source.DocumentID] = source
	}

	chunks := make([]Chunk, 0, len(eval.Chunks))
	chunkIDs := make(map[string]bool, len(eval.Chunks))
	for _, raw := range eval.Chunks {
		source, ok := sources[raw.DocumentID]
		if !ok {
			return EvalSet{}, nil, fmt.Errorf("chunk %q references unknown document", raw.ChunkID)
		}
		digest := sha256.Sum256([]byte(raw.Text))
		chunk := Chunk{
			SchemaVersion: ChunkSchemaV1, ChunkID: raw.ChunkID, DocumentID: raw.DocumentID,
			CompanyID: source.CompanyID, EvidenceType: source.EvidenceType, FilingID: source.FilingID,
			AccessionNumber: source.AccessionNumber, FormType: source.FormType, DocumentType: source.DocumentType,
			AuthorityTier: source.AuthorityTier, Issuer: source.Issuer, Language: source.Language,
			RightsClass: source.RightsClass, Audited: source.Audited, FiledWithSEC: source.FiledWithSEC,
			ForwardLooking: source.ForwardLooking, Promotional: source.Promotional, PublishedAt: source.PublishedAt,
			EffectiveAt: source.EffectiveAt, SupersededAt: source.SupersededAt,
			Section: raw.Section, Page: raw.Page, Locator: raw.Locator,
			Periods: append([]string(nil), raw.Periods...), ClaimKey: raw.ClaimKey, ClaimValue: raw.ClaimValue,
			Text: raw.Text, SourceURI: source.SourceURI, DocumentSHA256: source.DocumentSHA256,
			ContentSHA256: hex.EncodeToString(digest[:]), AvailableAt: source.AvailableAt,
			RetrievedAt: source.RetrievedAt, TokenEstimate: len([]rune(raw.Text))/4 + 1,
			ChunkingVersion: "filing-aware/v1",
		}
		if err := ValidateChunk(chunk); err != nil {
			return EvalSet{}, nil, fmt.Errorf("chunk %q: %w", raw.ChunkID, err)
		}
		if chunkIDs[chunk.ChunkID] {
			return EvalSet{}, nil, errors.New("duplicate retrieval evaluation chunk")
		}
		chunkIDs[chunk.ChunkID] = true
		chunks = append(chunks, chunk)
	}
	for _, question := range eval.Questions {
		if question.QuestionID == "" || question.Text == "" || question.TopK <= 0 || len(question.RelevantChunkIDs) == 0 {
			return EvalSet{}, nil, errors.New("invalid retrieval evaluation question")
		}
		for _, chunkID := range question.RelevantChunkIDs {
			if !chunkIDs[chunkID] {
				return EvalSet{}, nil, fmt.Errorf("question %q references unknown chunk %q", question.QuestionID, chunkID)
			}
		}
	}
	return eval, chunks, nil
}

func Measure(eval EvalSet, results map[string][]Hit) (EvalMetrics, error) {
	metrics := EvalMetrics{QuestionCount: len(eval.Questions)}
	if len(eval.Questions) == 0 {
		return metrics, errors.New("evaluation questions are required")
	}
	var recall, precision, complete, citations, contextTokens float64
	for _, question := range eval.Questions {
		hits, ok := results[question.QuestionID]
		if !ok {
			return metrics, fmt.Errorf("missing results for question %q", question.QuestionID)
		}
		if len(hits) > question.TopK {
			hits = hits[:question.TopK]
		}
		relevant := make(map[string]bool, len(question.RelevantChunkIDs))
		for _, id := range question.RelevantChunkIDs {
			relevant[id] = true
		}
		found := make(map[string]bool)
		validCitations := 0
		for _, hit := range hits {
			if relevant[hit.Chunk.ChunkID] {
				found[hit.Chunk.ChunkID] = true
			}
			if ValidateChunk(hit.Chunk) == nil && !hit.Chunk.AvailableAt.After(eval.AsOf) {
				validCitations++
			}
			contextTokens += float64(hit.Chunk.TokenEstimate)
		}
		recall += float64(len(found)) / float64(len(relevant))
		if len(hits) > 0 {
			precision += float64(len(found)) / float64(len(hits))
			citations += float64(validCitations) / float64(len(hits))
		}
		if len(found) == len(relevant) {
			complete++
		}
	}
	count := float64(len(eval.Questions))
	metrics.RecallAtK = recall / count
	metrics.PrecisionAtK = precision / count
	metrics.CompleteEvidenceRate = complete / count
	metrics.CitationCorrectness = citations / count
	metrics.MeanContextTokens = contextTokens / count
	return metrics, nil
}

func StableQuestionIDs(eval EvalSet) []string {
	ids := make([]string, 0, len(eval.Questions))
	for _, question := range eval.Questions {
		ids = append(ids, question.QuestionID)
	}
	sort.Strings(ids)
	return ids
}
