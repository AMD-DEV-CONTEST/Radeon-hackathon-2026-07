package productscope

import (
	"errors"
	"fmt"
	"sort"
	"time"
)

const (
	StandaloneJourneySuiteSchemaV1 = "signalforge/technology20-standalone-journeys/v1"
	StandaloneJourneyPolicyV1      = "technology20-standalone-journey-policy/v1"
	StandaloneDevelopmentSplit     = "development"
	StandaloneAugmentationSplit    = "development_augmentation"
	StandaloneSealedSplit          = "sealed_holdout"
)

type StandaloneJourneySuite struct {
	SchemaVersion string                  `json:"schema_version"`
	UniverseID    string                  `json:"universe_id"`
	Split         string                  `json:"split"`
	AsOf          time.Time               `json:"as_of"`
	PolicyVersion string                  `json:"policy_version"`
	Cases         []StandaloneJourneyCase `json:"cases"`
	ClaimBoundary string                  `json:"claim_boundary"`
}

type StandaloneJourneyCase struct {
	JourneyID           string   `json:"journey_id"`
	CompanyID           string   `json:"company_id"`
	PrimaryTicker       string   `json:"primary_ticker"`
	QuestionID          string   `json:"question_id"`
	Question            string   `json:"question"`
	RequiredDomains     []string `json:"required_domains"`
	ExpectedReceipts    []string `json:"expected_receipts"`
	ExpectedAbstentions []string `json:"expected_abstentions"`
	ExpectedDisposition string   `json:"expected_disposition"`
	FinancialReportSHA  string   `json:"financial_report_sha256"`
}

type journeyTemplate struct {
	ID         string
	Split      string
	Domains    []string
	Operations []string
	Question   func(PublicCompany) string
}

var standaloneTemplates = []journeyTemplate{
	{
		ID: "fundamentals", Split: StandaloneDevelopmentSplit,
		Domains: []string{"accounting", "financial_quality"},
		Operations: []string{
			"financial.revenue_growth", "financial.operating_margin", "financial.cash_conversion",
		},
		Question: func(company PublicCompany) string {
			return fmt.Sprintf("Using only point-in-time authorized evidence, explain %s's latest revenue growth, operating margin, and cash conversion. State unavailable measures explicitly.", company.DisplayName)
		},
	},
	{
		ID: "cash-quality", Split: StandaloneDevelopmentSplit,
		Domains: []string{"financial_quality"},
		Operations: []string{
			"financial.free_cash_flow", "financial.capex_intensity", "financial.quality_of_earnings",
		},
		Question: func(company PublicCompany) string {
			return fmt.Sprintf("Assess %s's cash-generation quality using operating cash flow, approved capex, simple FCF, and earnings quality. Do not present simple FCF as FCFF.", company.DisplayName)
		},
	},
	{
		ID: "accounting-integrity", Split: StandaloneDevelopmentSplit,
		Domains:    []string{"accounting"},
		Operations: []string{"accounting.balance_sheet_identity"},
		Question: func(company PublicCompany) string {
			return fmt.Sprintf("Check %s's latest available balance-sheet identity and explain the period, perimeter, and evidence limitations.", company.DisplayName)
		},
	},
	{
		ID: "risk-monitoring", Split: StandaloneDevelopmentSplit,
		Domains:    []string{"business", "market_behavior", "evidence"},
		Operations: []string{"narrative.investor_relations"},
		Question: func(company PublicCompany) string {
			return fmt.Sprintf("Identify the main operating risks and monitoring conditions for %s, separating filed facts, management assertions, and hypotheses.", company.DisplayName)
		},
	},
	{
		ID: "business-model", Split: StandaloneSealedSplit,
		Domains:    []string{"business", "evidence"},
		Operations: []string{"narrative.investor_relations"},
		Question: func(company PublicCompany) string {
			return fmt.Sprintf("Explain how %s makes money, its main operating segments, and the evidence that would confirm or challenge that description.", company.DisplayName)
		},
	},
	{
		ID: "valuation-macro", Split: StandaloneSealedSplit,
		Domains:    []string{"valuation", "economics", "market_behavior"},
		Operations: []string{"valuation.fcff_dcf", "valuation.peer_multiple", "macro.transmission"},
		Question: func(company PublicCompany) string {
			return fmt.Sprintf("Build a point-in-time valuation and macro-transmission view for %s, disclosing every price, vintage, assumption, and unavailable input.", company.DisplayName)
		},
	},
}

var standaloneAugmentationTemplates = []journeyTemplate{
	{
		ID: "economics-transmission", Split: StandaloneAugmentationSplit,
		Domains:    []string{"business", "economics", "evidence"},
		Operations: []string{"economics.yield_curve"},
		Question: func(company PublicCompany) string {
			return fmt.Sprintf(
				"Under an explicit higher-for-longer interest-rate and inflation scenario, explain how those economic variables could transmit through %s's demand, operations, financing, and cash generation. Keep scenario hypotheses separate from observed facts and state unavailable point-in-time macro inputs.",
				company.DisplayName,
			)
		},
	},
	{
		ID: "valuation-readiness", Split: StandaloneAugmentationSplit,
		Domains: []string{"evidence", "financial_quality", "valuation"},
		Operations: []string{
			"scenario.sensitivity_matrix", "valuation.fcff_dcf", "valuation.peer_multiple",
		},
		Question: func(company PublicCompany) string {
			return fmt.Sprintf(
				"Assess whether a point-in-time DCF value range and peer multiple can be responsibly produced for %s. Distinguish simple FCF from FCFF, expose every required assumption and market input, and return a typed limitation rather than inventing any unavailable value.",
				company.DisplayName,
			)
		},
	},
	{
		ID: "thesis-monitoring", Split: StandaloneAugmentationSplit,
		Domains:    []string{"business", "evidence", "market_behavior", "risk"},
		Operations: []string{"narrative.investor_relations"},
		Question: func(company PublicCompany) string {
			return fmt.Sprintf(
				"Challenge a thesis about %s using authorized evidence. Identify contrary evidence, testable invalidation conditions, and monitoring questions while separating filed facts, management assertions, and hypotheses. State when current narrative or market evidence is unavailable.",
				company.DisplayName,
			)
		},
	},
}

func BuildStandaloneJourneySuites(
	catalog PublicCatalog,
	financials PublicFinancialSummary,
) (StandaloneJourneySuite, StandaloneJourneySuite, error) {
	if err := ValidatePublicCatalog(catalog); err != nil {
		return StandaloneJourneySuite{}, StandaloneJourneySuite{}, err
	}
	if err := ValidatePublicFinancialSummary(financials); err != nil {
		return StandaloneJourneySuite{}, StandaloneJourneySuite{}, err
	}
	financialByCompany := map[string]PublicCompanyFinancials{}
	for _, company := range financials.Companies {
		financialByCompany[company.CompanyID] = company
	}
	base := func(split string) StandaloneJourneySuite {
		return StandaloneJourneySuite{
			SchemaVersion: StandaloneJourneySuiteSchemaV1, UniverseID: UniverseID,
			Split: split, AsOf: catalog.AsOf, PolicyVersion: StandaloneJourneyPolicyV1,
			ClaimBoundary: "Expected receipts and abstentions test routing and evidence behavior. They are not answer text, investment advice, or proof that a company is research_ready.",
		}
	}
	development, sealed := base(StandaloneDevelopmentSplit), base(StandaloneSealedSplit)
	for _, company := range catalog.Companies {
		financial, ok := financialByCompany[company.CompanyID]
		if !ok {
			return StandaloneJourneySuite{}, StandaloneJourneySuite{}, errors.New("standalone journey population is missing financial authority")
		}
		for _, template := range standaloneTemplates {
			item := buildStandaloneJourneyCase(company, financial, template)
			if template.Split == StandaloneDevelopmentSplit {
				development.Cases = append(development.Cases, item)
			} else {
				sealed.Cases = append(sealed.Cases, item)
			}
		}
	}
	if err := ValidateStandaloneJourneySuite(development, 80); err != nil {
		return StandaloneJourneySuite{}, StandaloneJourneySuite{}, err
	}
	if err := ValidateStandaloneJourneySuite(sealed, 40); err != nil {
		return StandaloneJourneySuite{}, StandaloneJourneySuite{}, err
	}
	return development, sealed, nil
}

// BuildStandaloneDevelopmentAugmentationSuite creates an inspectable development-only population.
// It has no sealed-output parameter and never reads the sealed Sprint 32 population.
func BuildStandaloneDevelopmentAugmentationSuite(
	catalog PublicCatalog,
	financials PublicFinancialSummary,
) (StandaloneJourneySuite, error) {
	if err := ValidatePublicCatalog(catalog); err != nil {
		return StandaloneJourneySuite{}, err
	}
	if err := ValidatePublicFinancialSummary(financials); err != nil {
		return StandaloneJourneySuite{}, err
	}
	financialByCompany := map[string]PublicCompanyFinancials{}
	for _, company := range financials.Companies {
		financialByCompany[company.CompanyID] = company
	}
	suite := StandaloneJourneySuite{
		SchemaVersion: StandaloneJourneySuiteSchemaV1,
		UniverseID:    UniverseID,
		Split:         StandaloneAugmentationSplit,
		AsOf:          catalog.AsOf,
		PolicyVersion: StandaloneJourneyPolicyV1,
		ClaimBoundary: "This public development-only augmentation measures economics, valuation-readiness, and thesis-monitoring contracts. It contains no sealed prompts or answer labels and does not promote a company or release.",
	}
	for _, company := range catalog.Companies {
		financial, ok := financialByCompany[company.CompanyID]
		if !ok {
			return StandaloneJourneySuite{}, errors.New("standalone journey augmentation is missing financial authority")
		}
		for _, template := range standaloneAugmentationTemplates {
			suite.Cases = append(suite.Cases, buildStandaloneJourneyCase(company, financial, template))
		}
	}
	if err := ValidateStandaloneJourneySuite(suite, 60); err != nil {
		return StandaloneJourneySuite{}, err
	}
	return suite, nil
}

func buildStandaloneJourneyCase(
	company PublicCompany,
	financial PublicCompanyFinancials,
	template journeyTemplate,
) StandaloneJourneyCase {
	available := map[string]bool{}
	for _, result := range financial.Results {
		available[result.OperationID] = true
	}
	item := StandaloneJourneyCase{
		JourneyID: fmt.Sprintf("%s-%s", company.PrimaryTicker, template.ID),
		CompanyID: company.CompanyID, PrimaryTicker: company.PrimaryTicker,
		QuestionID: template.ID, Question: template.Question(company),
		RequiredDomains:     append([]string(nil), template.Domains...),
		ExpectedReceipts:    []string{},
		ExpectedAbstentions: []string{},
		FinancialReportSHA:  financial.ReportSHA256,
	}
	for _, operation := range template.Operations {
		if available[operation] {
			item.ExpectedReceipts = append(item.ExpectedReceipts, operation)
		} else {
			item.ExpectedAbstentions = append(item.ExpectedAbstentions, operation)
		}
	}
	switch {
	case len(item.ExpectedReceipts) > 0 && len(item.ExpectedAbstentions) > 0:
		item.ExpectedDisposition = "mixed"
	case len(item.ExpectedReceipts) > 0:
		item.ExpectedDisposition = "deterministic_supported"
	default:
		item.ExpectedDisposition = "typed_abstention"
	}
	sort.Strings(item.ExpectedReceipts)
	sort.Strings(item.ExpectedAbstentions)
	return item
}

func ValidateStandaloneJourneySuite(suite StandaloneJourneySuite, expectedCases int) error {
	if suite.SchemaVersion != StandaloneJourneySuiteSchemaV1 || suite.UniverseID != UniverseID ||
		suite.AsOf.IsZero() || suite.PolicyVersion != StandaloneJourneyPolicyV1 ||
		!validStandaloneSplit(suite.Split) || suite.ClaimBoundary == "" ||
		len(suite.Cases) != expectedCases {
		return errors.New("standalone journey suite envelope is invalid")
	}
	seen := map[string]bool{}
	companies := map[string]int{}
	for _, item := range suite.Cases {
		if item.JourneyID == "" || seen[item.JourneyID] || item.CompanyID == "" ||
			item.PrimaryTicker == "" || item.QuestionID == "" || item.Question == "" ||
			len(item.RequiredDomains) == 0 || item.ExpectedDisposition == "" ||
			item.FinancialReportSHA == "" {
			return errors.New("standalone journey suite contains an invalid case")
		}
		if len(item.ExpectedReceipts)+len(item.ExpectedAbstentions) == 0 {
			return errors.New("standalone journey case has no expected authority outcome")
		}
		seen[item.JourneyID] = true
		companies[item.CompanyID]++
	}
	expectedPerCompany := expectedCases / len(Companies())
	if len(companies) != len(Companies()) {
		return errors.New("standalone journey suite does not cover all companies")
	}
	for _, count := range companies {
		if count != expectedPerCompany {
			return errors.New("standalone journey suite is not balanced by company")
		}
	}
	return nil
}

func validStandaloneSplit(split string) bool {
	return split == StandaloneDevelopmentSplit ||
		split == StandaloneAugmentationSplit ||
		split == StandaloneSealedSplit
}
