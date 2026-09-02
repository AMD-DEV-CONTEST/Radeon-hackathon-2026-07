package secparse

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/rvbernucci/signalforge/internal/data"
	"github.com/rvbernucci/signalforge/internal/rawstore"
)

const ParserVersion = "sec-json/v1"

type HistoricalFile struct {
	Name        string `json:"name"`
	FilingCount int    `json:"filing_count"`
	FilingFrom  string `json:"filing_from"`
	FilingTo    string `json:"filing_to"`
}

type filingColumns struct {
	AccessionNumber       []string `json:"accessionNumber"`
	FilingDate            []string `json:"filingDate"`
	ReportDate            []string `json:"reportDate"`
	AcceptanceDateTime    []string `json:"acceptanceDateTime"`
	Form                  []string `json:"form"`
	PrimaryDocument       []string `json:"primaryDocument"`
	PrimaryDocDescription []string `json:"primaryDocDescription"`
	IsXBRL                []int    `json:"isXBRL"`
	IsInlineXBRL          []int    `json:"isInlineXBRL"`
}

type submissionsPayload struct {
	CIK                  string `json:"cik"`
	Name                 string `json:"name"`
	SIC                  string `json:"sic"`
	FiscalYearEnd        string `json:"fiscalYearEnd"`
	StateOfIncorporation string `json:"stateOfIncorporation"`
	FormerNames          []struct {
		Name string `json:"name"`
	} `json:"formerNames"`
	Filings struct {
		Recent filingColumns    `json:"recent"`
		Files  []HistoricalFile `json:"files"`
	} `json:"filings"`
}

func ParseSubmissions(content []byte, record rawstore.Record) (data.Company, []data.Filing, []HistoricalFile, error) {
	var payload submissionsPayload
	if err := json.Unmarshal(content, &payload); err != nil {
		return data.Company{}, nil, nil, fmt.Errorf("decode SEC submissions: %w", err)
	}
	cik, err := data.CanonicalCIK(payload.CIK)
	if err != nil {
		return data.Company{}, nil, nil, err
	}
	formerNames := make([]string, 0, len(payload.FormerNames))
	for _, former := range payload.FormerNames {
		if name := strings.TrimSpace(former.Name); name != "" {
			formerNames = append(formerNames, name)
		}
	}
	company := data.Company{
		CompanyID: "sec-cik:" + cik, CIK: cik, LegalName: strings.TrimSpace(payload.Name),
		FormerNames: formerNames, Jurisdiction: payload.StateOfIncorporation,
		FiscalYearEnd: payload.FiscalYearEnd, SICCode: payload.SIC, Status: "active",
		ValidFrom: record.RetrievedAt, SourceRecordIDs: []string{record.RecordID}, RetrievedAt: record.RetrievedAt,
	}
	filings, err := parseFilingColumns(payload.Filings.Recent, company.CompanyID, record)
	if err != nil {
		return data.Company{}, nil, nil, err
	}
	for _, filing := range filings {
		if filing.AcceptedAt.Before(company.ValidFrom) {
			company.ValidFrom = filing.AcceptedAt
		}
	}
	if err := data.ValidateCompany(company); err != nil {
		return data.Company{}, nil, nil, err
	}
	return company, linkAmendments(filings), payload.Filings.Files, nil
}

func ParseHistoricalSubmissions(content []byte, companyID string, record rawstore.Record) ([]data.Filing, error) {
	var columns filingColumns
	if err := json.Unmarshal(content, &columns); err != nil {
		return nil, fmt.Errorf("decode SEC historical submissions: %w", err)
	}
	return parseFilingColumns(columns, companyID, record)
}

func MergeFilings(groups ...[]data.Filing) ([]data.Filing, error) {
	byAccession := map[string]data.Filing{}
	for _, group := range groups {
		for _, filing := range group {
			if existing, ok := byAccession[filing.AccessionNumber]; ok && existing != filing {
				return nil, fmt.Errorf("conflicting filing %s", filing.AccessionNumber)
			}
			byAccession[filing.AccessionNumber] = filing
		}
	}
	result := make([]data.Filing, 0, len(byAccession))
	for _, filing := range byAccession {
		result = append(result, filing)
	}
	sort.Slice(result, func(i, j int) bool {
		if result[i].AcceptedAt.Equal(result[j].AcceptedAt) {
			return result[i].AccessionNumber < result[j].AccessionNumber
		}
		return result[i].AcceptedAt.Before(result[j].AcceptedAt)
	})
	return linkAmendments(result), nil
}

func parseFilingColumns(columns filingColumns, companyID string, record rawstore.Record) ([]data.Filing, error) {
	count := len(columns.AccessionNumber)
	if count == 0 {
		return nil, nil
	}
	required := map[string]int{
		"filingDate": len(columns.FilingDate), "reportDate": len(columns.ReportDate),
		"acceptanceDateTime": len(columns.AcceptanceDateTime), "form": len(columns.Form),
		"primaryDocument": len(columns.PrimaryDocument), "primaryDocDescription": len(columns.PrimaryDocDescription),
		"isXBRL": len(columns.IsXBRL), "isInlineXBRL": len(columns.IsInlineXBRL),
	}
	for name, length := range required {
		if length != count {
			return nil, fmt.Errorf("SEC filing column %s has %d rows; expected %d", name, length, count)
		}
	}
	result := make([]data.Filing, 0, count)
	for index := 0; index < count; index++ {
		filedAt, err := time.Parse("2006-01-02", columns.FilingDate[index])
		if err != nil {
			return nil, fmt.Errorf("filing %d filingDate: %w", index, err)
		}
		acceptedAt, err := parseSECTimestamp(columns.AcceptanceDateTime[index])
		if err != nil {
			return nil, fmt.Errorf("filing %d acceptanceDateTime: %w", index, err)
		}
		reportAt := filedAt
		inferred := strings.TrimSpace(columns.ReportDate[index]) == ""
		if !inferred {
			reportAt, err = time.Parse("2006-01-02", columns.ReportDate[index])
			if err != nil {
				return nil, fmt.Errorf("filing %d reportDate: %w", index, err)
			}
		}
		filing := data.Filing{
			FilingID: "sec-filing:" + columns.AccessionNumber[index], CompanyID: companyID,
			AccessionNumber: columns.AccessionNumber[index], FormType: columns.Form[index],
			ReportPeriodEnd: reportAt.UTC(), FiledAt: filedAt.UTC(), AcceptedAt: acceptedAt,
			PublishedAt: acceptedAt, PrimaryDocument: columns.PrimaryDocument[index],
			PrimaryDocTitle: columns.PrimaryDocDescription[index], ReportInferred: inferred,
			IsXBRL: columns.IsXBRL[index] == 1, IsInlineXBRL: columns.IsInlineXBRL[index] == 1,
			SourceRecordID: record.RecordID, SourceURI: record.SourceURI,
			ContentSHA256: record.ContentSHA, RetrievedAt: record.RetrievedAt, ExtractorVersion: ParserVersion,
		}
		if err := data.ValidateFiling(filing); err != nil {
			return nil, fmt.Errorf("filing %d: %w", index, err)
		}
		result = append(result, filing)
	}
	return result, nil
}

func parseSECTimestamp(value string) (time.Time, error) {
	for _, layout := range []string{time.RFC3339Nano, "2006-01-02T15:04:05.000Z", "20060102150405"} {
		if parsed, err := time.Parse(layout, value); err == nil {
			return parsed.UTC(), nil
		}
	}
	return time.Time{}, errors.New("unsupported SEC timestamp")
}

func linkAmendments(filings []data.Filing) []data.Filing {
	result := append([]data.Filing(nil), filings...)
	sort.SliceStable(result, func(i, j int) bool { return result[i].AcceptedAt.Before(result[j].AcceptedAt) })
	for index := range result {
		if !strings.HasSuffix(result[index].FormType, "/A") {
			continue
		}
		base := strings.TrimSuffix(result[index].FormType, "/A")
		for candidate := index - 1; candidate >= 0; candidate-- {
			if result[candidate].FormType == base && result[candidate].ReportPeriodEnd.Equal(result[index].ReportPeriodEnd) {
				result[index].AmendsFilingID = result[candidate].FilingID
				break
			}
		}
	}
	return result
}

func stableID(parts ...string) string {
	digest := sha256.Sum256([]byte(strings.Join(parts, "\x1f")))
	return hex.EncodeToString(digest[:])
}
