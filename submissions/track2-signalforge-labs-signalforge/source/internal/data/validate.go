package data

import (
	"errors"
	"fmt"
	"regexp"
	"sort"
	"strings"
	"time"
)

var (
	cikPattern       = regexp.MustCompile(`^[0-9]{10}$`)
	accessionPattern = regexp.MustCompile(`^[0-9]{10}-[0-9]{2}-[0-9]{6}$`)
)

func IsAvailableAsOf(availability Availability, asOf time.Time) bool {
	if asOf.IsZero() || availability.AvailableAt.IsZero() {
		return false
	}
	return !availability.AvailableAt.After(asOf)
}

func CanonicalCIK(value string) (string, error) {
	value = strings.TrimSpace(value)
	if value == "" || len(value) > 10 {
		return "", errors.New("CIK must contain between one and ten digits")
	}
	for _, character := range value {
		if character < '0' || character > '9' {
			return "", errors.New("CIK must contain digits only")
		}
	}
	return strings.Repeat("0", 10-len(value)) + value, nil
}

func ValidateCompany(company Company) error {
	if company.CompanyID == "" || company.LegalName == "" || !cikPattern.MatchString(company.CIK) {
		return errors.New("company_id, legal_name, and zero-padded ten-digit CIK are required")
	}
	if company.ValidFrom.IsZero() || company.RetrievedAt.IsZero() || len(company.SourceRecordIDs) == 0 {
		return errors.New("valid_from, retrieved_at, and source_record_ids are required")
	}
	if company.ValidTo != nil && company.ValidTo.Before(company.ValidFrom) {
		return errors.New("valid_to cannot precede valid_from")
	}
	return nil
}

func ValidateFiling(filing Filing) error {
	if filing.FilingID == "" || filing.CompanyID == "" || !accessionPattern.MatchString(filing.AccessionNumber) {
		return errors.New("filing_id, company_id, and canonical accession_number are required")
	}
	if filing.FormType == "" || filing.SourceRecordID == "" || filing.SourceURI == "" || filing.ContentSHA256 == "" || filing.ExtractorVersion == "" {
		return errors.New("form_type, source record, source_uri, content hash, and extractor_version are required")
	}
	if filing.ReportPeriodEnd.IsZero() || filing.FiledAt.IsZero() || filing.AcceptedAt.IsZero() || filing.PublishedAt.IsZero() || filing.RetrievedAt.IsZero() {
		return errors.New("all filing timestamps are required")
	}
	if filing.PublishedAt.Before(filing.AcceptedAt) {
		return errors.New("published_at cannot precede accepted_at")
	}
	if filing.RetrievedAt.Before(filing.PublishedAt) {
		return errors.New("retrieved_at cannot precede published_at")
	}
	if filing.AmendsFilingID != "" && filing.AmendsFilingID == filing.FilingID {
		return errors.New("filing cannot amend itself")
	}
	return nil
}

func ValidateReportedFact(fact ReportedFact) error {
	if fact.FactID == "" || fact.FilingID == "" || fact.CompanyID == "" || fact.Taxonomy == "" || fact.Concept == "" {
		return errors.New("fact identity, taxonomy, and concept are required")
	}
	if strings.TrimSpace(fact.Value) == "" || fact.Unit == "" || fact.FormType == "" || fact.SourceContextID == "" || fact.SourceLocator == "" {
		return errors.New("value, unit, form_type, source_context_id, and source_locator are required")
	}
	if fact.AvailableAt.IsZero() || fact.RetrievedAt.IsZero() {
		return errors.New("available_at and retrieved_at are required")
	}
	if fact.RetrievedAt.Before(fact.AvailableAt) {
		return errors.New("retrieved_at cannot precede available_at")
	}
	duration := fact.StartDate != nil || fact.EndDate != nil
	instant := fact.InstantDate != nil
	if duration == instant {
		return errors.New("fact must be exactly one of duration or instant")
	}
	if duration {
		if fact.StartDate == nil || fact.EndDate == nil {
			return errors.New("duration fact requires start_date and end_date")
		}
		if fact.EndDate.Before(*fact.StartDate) {
			return errors.New("end_date cannot precede start_date")
		}
		if fact.AvailableAt.Before(*fact.EndDate) {
			return errors.New("duration fact cannot be available before period end")
		}
	} else if fact.AvailableAt.Before(*fact.InstantDate) {
		return errors.New("instant fact cannot be available before its instant date")
	}
	return nil
}

func ValidateNormalizedMetric(metric NormalizedMetric) error {
	if metric.MetricID == "" || metric.CompanyID == "" || metric.CanonicalMetric == "" {
		return errors.New("metric_id, company_id, and canonical_metric are required")
	}
	if metric.Value == "" || metric.Unit == "" || metric.PeriodType == "" {
		return errors.New("value, unit, and period_type are required")
	}
	if metric.PeriodStart.IsZero() || metric.PeriodEnd.IsZero() || metric.PeriodEnd.Before(metric.PeriodStart) {
		return errors.New("metric requires a valid period")
	}
	if len(metric.SourceFactIDs) == 0 || metric.TransformationID == "" || metric.NormalizationPolicy == "" {
		return errors.New("source facts, transformation, and normalization policy are required")
	}
	if metric.SourceAvailableAt.IsZero() || metric.ComputedAt.IsZero() {
		return errors.New("source_available_at and computed_at are required")
	}
	if metric.ComputedAt.Before(metric.SourceAvailableAt) {
		return fmt.Errorf("computed_at cannot precede source_available_at")
	}
	return nil
}

func ValidateFilingSet(filings []Filing) error {
	byID := make(map[string]Filing, len(filings))
	accessions := make(map[string]bool, len(filings))
	periodForms := make(map[string]string, len(filings))
	for index, filing := range filings {
		if err := ValidateFiling(filing); err != nil {
			return fmt.Errorf("filings[%d]: %w", index, err)
		}
		if _, duplicate := byID[filing.FilingID]; duplicate || accessions[filing.AccessionNumber] {
			return fmt.Errorf("filings[%d] duplicates filing or accession identity", index)
		}
		key := strings.Join([]string{filing.CompanyID, filing.ReportPeriodEnd.Format("2006-01-02"), baseForm(filing.FormType)}, "|")
		if prior, exists := periodForms[key]; exists && filing.AmendsFilingID == "" {
			return fmt.Errorf("filings[%d] duplicates period/form without amendment lineage to %q", index, prior)
		}
		periodForms[key] = filing.FilingID
		byID[filing.FilingID] = filing
		accessions[filing.AccessionNumber] = true
	}
	for index, filing := range filings {
		if filing.AmendsFilingID == "" {
			continue
		}
		parent, exists := byID[filing.AmendsFilingID]
		if !exists || parent.CompanyID != filing.CompanyID {
			return fmt.Errorf("filings[%d] amendment target is missing or belongs to another company", index)
		}
		if !filing.PublishedAt.After(parent.PublishedAt) || baseForm(parent.FormType) != baseForm(filing.FormType) {
			return fmt.Errorf("filings[%d] amendment order or form family is invalid", index)
		}
		seen := map[string]bool{filing.FilingID: true}
		cursor := parent
		for {
			if seen[cursor.FilingID] {
				return fmt.Errorf("filings[%d] amendment lineage contains a cycle", index)
			}
			seen[cursor.FilingID] = true
			if cursor.AmendsFilingID == "" {
				break
			}
			next, ok := byID[cursor.AmendsFilingID]
			if !ok {
				return fmt.Errorf("filings[%d] amendment chain has a missing ancestor", index)
			}
			cursor = next
		}
	}
	return nil
}

func ActiveFilingsAsOf(filings []Filing, asOf time.Time) ([]Filing, error) {
	if asOf.IsZero() {
		return nil, errors.New("as_of is required")
	}
	if err := ValidateFilingSet(filings); err != nil {
		return nil, err
	}
	available := make(map[string]Filing, len(filings))
	superseded := map[string]bool{}
	for _, filing := range filings {
		if filing.PublishedAt.After(asOf) {
			continue
		}
		available[filing.FilingID] = filing
		if filing.AmendsFilingID != "" {
			superseded[filing.AmendsFilingID] = true
		}
	}
	result := make([]Filing, 0, len(available))
	for id, filing := range available {
		if !superseded[id] {
			result = append(result, filing)
		}
	}
	sort.Slice(result, func(i, j int) bool {
		if result[i].PublishedAt.Equal(result[j].PublishedAt) {
			return result[i].FilingID < result[j].FilingID
		}
		return result[i].PublishedAt.Before(result[j].PublishedAt)
	})
	return result, nil
}

func ValidateReportedFactSet(facts []ReportedFact) error {
	byID := make(map[string]bool, len(facts))
	identities := make(map[string]bool, len(facts))
	conceptPeriods := make(map[string]string, len(facts))
	for index, fact := range facts {
		if err := ValidateReportedFact(fact); err != nil {
			return fmt.Errorf("facts[%d]: %w", index, err)
		}
		if byID[fact.FactID] {
			return fmt.Errorf("facts[%d] duplicates fact_id %q", index, fact.FactID)
		}
		byID[fact.FactID] = true
		period := factPeriodKey(fact)
		dimensions := dimensionKey(fact.Dimensions)
		base := strings.Join([]string{fact.CompanyID, fact.FilingID, fact.Taxonomy, fact.Concept, period, dimensions}, "|")
		identity := base + "|" + fact.Unit
		if identities[identity] {
			return fmt.Errorf("facts[%d] duplicates concept, period, dimensions, and unit", index)
		}
		identities[identity] = true
		if priorUnit, exists := conceptPeriods[base]; exists && priorUnit != fact.Unit {
			return fmt.Errorf("facts[%d] conflicts with unit %q for the same concept and period", index, priorUnit)
		}
		conceptPeriods[base] = fact.Unit
	}
	return nil
}

func baseForm(value string) string {
	return strings.TrimSuffix(strings.ToUpper(strings.TrimSpace(value)), "/A")
}

func factPeriodKey(fact ReportedFact) string {
	if fact.InstantDate != nil {
		return "instant:" + fact.InstantDate.Format("2006-01-02")
	}
	return "duration:" + fact.StartDate.Format("2006-01-02") + ":" + fact.EndDate.Format("2006-01-02")
}

func dimensionKey(values map[string]string) string {
	keys := make([]string, 0, len(values))
	for key := range values {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	parts := make([]string, 0, len(keys))
	for _, key := range keys {
		parts = append(parts, key+"="+values[key])
	}
	return strings.Join(parts, ";")
}
