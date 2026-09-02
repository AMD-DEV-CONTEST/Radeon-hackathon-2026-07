package productscope

import (
	"errors"
	"sort"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
)

const PublicFinancialSummarySchemaV1 = "signalforge/technology20-public-financial-summary/v1"

type PublicFinancialSummary struct {
	SchemaVersion string                    `json:"schema_version"`
	UniverseID    string                    `json:"universe_id"`
	AsOf          time.Time                 `json:"as_of"`
	Companies     []PublicCompanyFinancials `json:"companies"`
	ClaimBoundary string                    `json:"claim_boundary"`
}

type PublicCompanyFinancials struct {
	CompanyID     string                      `json:"company_id"`
	PrimaryTicker string                      `json:"primary_ticker"`
	DisplayName   string                      `json:"display_name"`
	ReportSHA256  string                      `json:"report_sha256"`
	Results       []PublicFinancialResult     `json:"results"`
	Abstentions   []PublicFinancialAbstention `json:"abstentions"`
}

type PublicFinancialResult struct {
	OperationID    string                    `json:"operation_id"`
	FormulaVersion string                    `json:"formula_version"`
	Periods        []string                  `json:"periods"`
	SourceAsOf     time.Time                 `json:"source_as_of"`
	Outputs        []contracts.ReceiptOutput `json:"outputs"`
	EvidenceRefs   []string                  `json:"evidence_refs"`
	ReceiptSHA256  string                    `json:"receipt_sha256"`
}

type PublicFinancialAbstention struct {
	OperationID string `json:"operation_id"`
	Code        string `json:"code"`
	Message     string `json:"message"`
}

func BuildPublicFinancialSummary(
	catalog PublicCatalog,
	reports map[string]CompanyFinancialActivation,
) (PublicFinancialSummary, error) {
	if err := ValidatePublicCatalog(catalog); err != nil {
		return PublicFinancialSummary{}, err
	}
	summary := PublicFinancialSummary{
		SchemaVersion: PublicFinancialSummarySchemaV1,
		UniverseID:    UniverseID,
		AsOf:          catalog.AsOf,
		ClaimBoundary: "These values are deterministic, point-in-time research outputs, not investment advice. Simple FCF means operating cash flow minus the approved capex concept; it is not FCFF. Missing authority produces a visible abstention.",
	}
	for _, company := range catalog.Companies {
		report, ok := reports[company.CompanyID]
		if !ok {
			return PublicFinancialSummary{}, errors.New("public financial summary is missing a company report")
		}
		if err := ValidateCompanyFinancialActivation(report); err != nil {
			return PublicFinancialSummary{}, err
		}
		item := PublicCompanyFinancials{
			CompanyID: company.CompanyID, PrimaryTicker: company.PrimaryTicker,
			DisplayName: company.DisplayName, ReportSHA256: report.ReportSHA256,
		}
		for _, receipt := range report.Receipts {
			item.Results = append(item.Results, PublicFinancialResult{
				OperationID: receipt.OperationID, FormulaVersion: receipt.FormulaVersion,
				Periods: append([]string(nil), receipt.Scope.Periods...), SourceAsOf: receipt.SourceAsOf,
				Outputs:       append([]contracts.ReceiptOutput(nil), receipt.Outputs...),
				EvidenceRefs:  append([]string(nil), receipt.EvidenceRefs...),
				ReceiptSHA256: receipt.ReceiptSHA,
			})
		}
		for _, abstention := range report.Abstentions {
			item.Abstentions = append(item.Abstentions, PublicFinancialAbstention{
				OperationID: abstention.MetricIDs[0], Code: abstention.Code, Message: abstention.Message,
			})
		}
		sort.Slice(item.Results, func(i, j int) bool {
			return item.Results[i].OperationID < item.Results[j].OperationID
		})
		sort.Slice(item.Abstentions, func(i, j int) bool {
			return item.Abstentions[i].OperationID < item.Abstentions[j].OperationID
		})
		summary.Companies = append(summary.Companies, item)
	}
	return summary, ValidatePublicFinancialSummary(summary)
}

func ValidatePublicFinancialSummary(summary PublicFinancialSummary) error {
	if summary.SchemaVersion != PublicFinancialSummarySchemaV1 ||
		summary.UniverseID != UniverseID || summary.AsOf.IsZero() ||
		len(summary.Companies) != len(Companies()) || summary.ClaimBoundary == "" {
		return errors.New("public financial summary envelope is invalid")
	}
	seen := map[string]bool{}
	for _, company := range summary.Companies {
		if company.CompanyID == "" || company.PrimaryTicker == "" || company.DisplayName == "" ||
			company.ReportSHA256 == "" || seen[company.CompanyID] ||
			len(company.Results)+len(company.Abstentions) !=
				len(companyOperationSpecs)+len(unavailableCompanyOperations) {
			return errors.New("public financial company summary is invalid")
		}
		seen[company.CompanyID] = true
		for _, result := range company.Results {
			if result.OperationID == "" || result.FormulaVersion == "" || result.SourceAsOf.IsZero() ||
				len(result.Outputs) == 0 || len(result.EvidenceRefs) == 0 || result.ReceiptSHA256 == "" {
				return errors.New("public financial result is invalid")
			}
		}
		for _, abstention := range company.Abstentions {
			if abstention.OperationID == "" || abstention.Code == "" || abstention.Message == "" {
				return errors.New("public financial abstention is invalid")
			}
		}
	}
	return nil
}
