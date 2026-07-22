package secparse

import (
	"bytes"
	"encoding/json"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/cockroachdb/apd/v3"
	"github.com/rvbernucci/signalforge/internal/data"
	"github.com/rvbernucci/signalforge/internal/rawstore"
)

type FactIssue struct {
	Taxonomy string `json:"taxonomy"`
	Concept  string `json:"concept"`
	Unit     string `json:"unit"`
	Index    int    `json:"index"`
	Reason   string `json:"reason"`
}

type companyFactsPayload struct {
	CIK        int64                                `json:"cik"`
	EntityName string                               `json:"entityName"`
	Facts      map[string]map[string]companyConcept `json:"facts"`
}

type companyConcept struct {
	Label       string                      `json:"label"`
	Description string                      `json:"description"`
	Units       map[string][]companyFactRow `json:"units"`
}

type companyFactRow struct {
	Start string          `json:"start"`
	End   string          `json:"end"`
	Value json.RawMessage `json:"val"`
	Accn  string          `json:"accn"`
	FY    *int            `json:"fy"`
	FP    string          `json:"fp"`
	Form  string          `json:"form"`
	Filed string          `json:"filed"`
	Frame string          `json:"frame"`
}

func FilingIndex(filings []data.Filing) (map[string]data.Filing, error) {
	result := make(map[string]data.Filing, len(filings))
	for _, filing := range filings {
		if existing, ok := result[filing.AccessionNumber]; ok && existing.FilingID != filing.FilingID {
			return nil, fmt.Errorf("duplicate accession %s", filing.AccessionNumber)
		}
		result[filing.AccessionNumber] = filing
	}
	return result, nil
}

func ParseCompanyFacts(content []byte, record rawstore.Record, filings map[string]data.Filing) ([]data.ReportedFact, []FactIssue, error) {
	decoder := json.NewDecoder(bytes.NewReader(content))
	decoder.UseNumber()
	var payload companyFactsPayload
	if err := decoder.Decode(&payload); err != nil {
		return nil, nil, fmt.Errorf("decode SEC company facts: %w", err)
	}
	cik, err := data.CanonicalCIK(fmt.Sprintf("%d", payload.CIK))
	if err != nil {
		return nil, nil, err
	}
	companyID := "sec-cik:" + cik
	var facts []data.ReportedFact
	var issues []FactIssue
	for taxonomy, concepts := range payload.Facts {
		for conceptName, concept := range concepts {
			for unit, rows := range concept.Units {
				for index, row := range rows {
					fact, reason := parseFactRow(companyID, taxonomy, conceptName, concept.Label, unit, index, row, record, filings)
					if reason != "" {
						issues = append(issues, FactIssue{Taxonomy: taxonomy, Concept: conceptName, Unit: unit, Index: index, Reason: reason})
						continue
					}
					facts = append(facts, fact)
				}
			}
		}
	}
	sort.Slice(facts, func(i, j int) bool {
		if facts[i].AvailableAt.Equal(facts[j].AvailableAt) {
			return facts[i].FactID < facts[j].FactID
		}
		return facts[i].AvailableAt.Before(facts[j].AvailableAt)
	})
	return facts, issues, nil
}

func parseFactRow(companyID, taxonomy, concept, label, unit string, index int, row companyFactRow,
	record rawstore.Record, filings map[string]data.Filing) (data.ReportedFact, string) {
	filing, ok := filings[row.Accn]
	if !ok {
		return data.ReportedFact{}, "filing_accession_not_found"
	}
	value := strings.TrimSpace(string(row.Value))
	if len(value) >= 2 && value[0] == '"' && value[len(value)-1] == '"' {
		if err := json.Unmarshal(row.Value, &value); err != nil {
			return data.ReportedFact{}, "invalid_string_value"
		}
	}
	if _, _, err := apd.NewFromString(value); err != nil {
		return data.ReportedFact{}, "non_decimal_value"
	}
	end, err := time.Parse("2006-01-02", row.End)
	if err != nil {
		return data.ReportedFact{}, "invalid_end_date"
	}
	var start *time.Time
	var durationEnd *time.Time
	var instant *time.Time
	if strings.TrimSpace(row.Start) == "" {
		instantValue := end.UTC()
		instant = &instantValue
	} else {
		startValue, err := time.Parse("2006-01-02", row.Start)
		if err != nil {
			return data.ReportedFact{}, "invalid_start_date"
		}
		startValue = startValue.UTC()
		start = &startValue
		endValue := end.UTC()
		durationEnd = &endValue
	}
	end = end.UTC()
	periodIdentity := end.Format("2006-01-02")
	if start != nil {
		periodIdentity = start.Format("2006-01-02") + ":" + periodIdentity
	}
	contextID := "sec-companyfacts:" + stableID(companyID, taxonomy, concept, unit, row.Accn, periodIdentity, value)
	fact := data.ReportedFact{
		FactID: contextID, FilingID: filing.FilingID, CompanyID: companyID,
		Taxonomy: taxonomy, Concept: concept, Label: label, Value: value, Unit: unit,
		StartDate: start, EndDate: durationEnd, InstantDate: instant, FiscalPeriod: row.FP,
		FormType: row.Form, CustomConcept: taxonomy != "us-gaap" && taxonomy != "dei",
		SourceContextID: contextID,
		SourceLocator:   fmt.Sprintf("companyfacts:%s/%s/%s/%d", taxonomy, concept, unit, index),
		AvailableAt:     filing.AcceptedAt, RetrievedAt: record.RetrievedAt,
	}
	if row.FY != nil {
		fact.FiscalYear = *row.FY
	}
	if err := data.ValidateReportedFact(fact); err != nil {
		return data.ReportedFact{}, "validation_failed:" + err.Error()
	}
	return fact, ""
}
