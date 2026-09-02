package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"sort"
	"time"

	"github.com/rvbernucci/signalforge/internal/retrieval"
)

type methodReport struct {
	Method       string                `json:"method"`
	ModelID      string                `json:"model_id,omitempty"`
	Revision     string                `json:"revision,omitempty"`
	Metrics      retrieval.EvalMetrics `json:"metrics"`
	Questions    []questionReport      `json:"questions"`
	LatencyP50US float64               `json:"latency_p50_us"`
	LatencyP95US float64               `json:"latency_p95_us"`
}

type questionReport struct {
	QuestionID string   `json:"question_id"`
	HitIDs     []string `json:"hit_ids"`
	MissingIDs []string `json:"missing_ids,omitempty"`
}

type report struct {
	SchemaVersion string         `json:"schema_version"`
	EvalPath      string         `json:"eval_path"`
	GeneratedAt   time.Time      `json:"generated_at"`
	Methods       []methodReport `json:"methods"`
}

func main() {
	evalPath := flag.String("eval", "fixtures/retrieval/golden-eval.json", "frozen retrieval evaluation JSON")
	vectorsPath := flag.String("vectors", "", "optional semantic vector fixture JSON")
	outputPath := flag.String("output", "", "optional output JSON path")
	flag.Parse()

	eval, chunks, err := retrieval.LoadEvalSet(*evalPath)
	if err != nil {
		fatal(err)
	}
	lexical, err := retrieval.NewLexicalIndex(chunks)
	if err != nil {
		fatal(err)
	}
	bm25Results, bm25Latency, err := run(eval, func(question retrieval.EvalQuestion) ([]retrieval.Hit, error) {
		return lexical.Search(retrieval.Query{Text: question.Text, AsOf: eval.AsOf, CompanyIDs: question.CompanyIDs, TopK: question.TopK})
	})
	if err != nil {
		fatal(err)
	}
	bm25Metrics, err := retrieval.Measure(eval, bm25Results)
	if err != nil {
		fatal(err)
	}
	p50, p95 := percentiles(bm25Latency)
	result := report{SchemaVersion: "signalforge/retrieval-benchmark/v1", EvalPath: *evalPath, GeneratedAt: time.Now().UTC(), Methods: []methodReport{{Method: "bm25/v1", Metrics: bm25Metrics, Questions: questionReports(eval, bm25Results), LatencyP50US: p50, LatencyP95US: p95}}}

	if *vectorsPath != "" {
		vectors, err := retrieval.LoadVectorFixture(*vectorsPath, chunks, eval)
		if err != nil {
			fatal(err)
		}
		chunkByID := make(map[string]retrieval.Chunk, len(chunks))
		for _, chunk := range chunks {
			chunkByID[chunk.ChunkID] = chunk
		}
		records := make([]retrieval.VectorRecord, 0, len(vectors.Chunks))
		for _, item := range vectors.Chunks {
			records = append(records, retrieval.VectorRecord{Chunk: chunkByID[item.ID], Vector: item.Vector})
		}
		semantic, err := retrieval.NewVectorIndex(records)
		if err != nil {
			fatal(err)
		}
		questionVectors := make(map[string][]float32, len(vectors.Questions))
		for _, item := range vectors.Questions {
			questionVectors[item.ID] = item.Vector
		}
		semanticResults, semanticLatency, err := run(eval, func(question retrieval.EvalQuestion) ([]retrieval.Hit, error) {
			return semantic.Search(retrieval.Query{Text: question.Text, AsOf: eval.AsOf, CompanyIDs: question.CompanyIDs, TopK: question.TopK}, questionVectors[question.QuestionID])
		})
		if err != nil {
			fatal(err)
		}
		semanticMetrics, _ := retrieval.Measure(eval, semanticResults)
		p50, p95 = percentiles(semanticLatency)
		result.Methods = append(result.Methods, methodReport{Method: "cosine/v1", ModelID: vectors.ModelID, Revision: vectors.Revision, Metrics: semanticMetrics, Questions: questionReports(eval, semanticResults), LatencyP50US: p50, LatencyP95US: p95})

		fused := make(map[string][]retrieval.Hit, len(eval.Questions))
		for _, question := range eval.Questions {
			fused[question.QuestionID] = retrieval.ReciprocalRankFusion([][]retrieval.Hit{bm25Results[question.QuestionID], semanticResults[question.QuestionID]}, question.TopK, 60)
		}
		fusedMetrics, _ := retrieval.Measure(eval, fused)
		result.Methods = append(result.Methods, methodReport{Method: "rrf-bm25-cosine/v1", ModelID: vectors.ModelID, Revision: vectors.Revision, Metrics: fusedMetrics, Questions: questionReports(eval, fused)})
		for _, candidate := range []struct {
			name    string
			weights []float64
		}{
			{name: "rrf-bm25-2-cosine-1/v1", weights: []float64{2, 1}},
			{name: "rrf-bm25-1-cosine-2/v1", weights: []float64{1, 2}},
		} {
			weighted := make(map[string][]retrieval.Hit, len(eval.Questions))
			for _, question := range eval.Questions {
				weighted[question.QuestionID] = retrieval.WeightedReciprocalRankFusion(
					[][]retrieval.Hit{bm25Results[question.QuestionID], semanticResults[question.QuestionID]},
					candidate.weights, question.TopK, 60,
				)
			}
			weightedMetrics, _ := retrieval.Measure(eval, weighted)
			result.Methods = append(result.Methods, methodReport{Method: candidate.name, ModelID: vectors.ModelID, Revision: vectors.Revision, Metrics: weightedMetrics, Questions: questionReports(eval, weighted)})
		}
	}

	encoded, err := json.MarshalIndent(result, "", "  ")
	if err != nil {
		fatal(err)
	}
	encoded = append(encoded, '\n')
	if *outputPath == "" {
		_, _ = os.Stdout.Write(encoded)
		return
	}
	if err := os.WriteFile(*outputPath, encoded, 0o640); err != nil {
		fatal(err)
	}
}

func questionReports(eval retrieval.EvalSet, results map[string][]retrieval.Hit) []questionReport {
	reports := make([]questionReport, 0, len(eval.Questions))
	for _, question := range eval.Questions {
		report := questionReport{QuestionID: question.QuestionID}
		found := make(map[string]struct{})
		for _, hit := range results[question.QuestionID] {
			report.HitIDs = append(report.HitIDs, hit.Chunk.ChunkID)
			found[hit.Chunk.ChunkID] = struct{}{}
		}
		for _, relevant := range question.RelevantChunkIDs {
			if _, ok := found[relevant]; !ok {
				report.MissingIDs = append(report.MissingIDs, relevant)
			}
		}
		reports = append(reports, report)
	}
	return reports
}

func run(eval retrieval.EvalSet, search func(retrieval.EvalQuestion) ([]retrieval.Hit, error)) (map[string][]retrieval.Hit, []float64, error) {
	results := make(map[string][]retrieval.Hit, len(eval.Questions))
	latencies := make([]float64, 0, len(eval.Questions)*20)
	for repetition := 0; repetition < 20; repetition++ {
		for _, question := range eval.Questions {
			started := time.Now()
			hits, err := search(question)
			elapsed := float64(time.Since(started).Nanoseconds()) / 1000
			if err != nil {
				return nil, nil, err
			}
			latencies = append(latencies, elapsed)
			if repetition == 0 {
				results[question.QuestionID] = hits
			}
		}
	}
	return results, latencies, nil
}

func percentiles(values []float64) (float64, float64) {
	sort.Float64s(values)
	return percentile(values, .50), percentile(values, .95)
}

func percentile(values []float64, quantile float64) float64 {
	if len(values) == 0 {
		return 0
	}
	index := int(float64(len(values)-1) * quantile)
	return values[index]
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, err)
	os.Exit(1)
}
