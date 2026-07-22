package data

import (
	"errors"
	"fmt"
	"regexp"
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
