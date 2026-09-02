package roles

func IRConsumerRoles(documentType string) []string {
	var consumers []string
	switch documentType {
	case "corporate_profile_and_history", "business_products_and_segments", "official_strategy_or_risk_update":
		consumers = []string{BusinessStrategy, RiskContrarian}
	case "earnings_release", "prepared_remarks", "official_earnings_transcript":
		consumers = []string{AccountingReporting, FinancialQuality, RiskContrarian}
	case "shareholder_letter", "investor_presentation", "investor_day_and_conference_material", "guidance_and_outlook", "capital_allocation_update":
		consumers = []string{BusinessStrategy, FinancialQuality, RiskContrarian}
	case "governance_document", "board_and_committee_material", "annual_meeting_material":
		consumers = []string{RiskContrarian}
	default:
		return nil
	}
	return append(consumers, EvidenceCritic)
}
