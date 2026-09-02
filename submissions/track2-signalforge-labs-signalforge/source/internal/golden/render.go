package golden

import (
	"fmt"
	"sort"
	"strings"
)

func RenderMarkdown(report Report) string {
	var output strings.Builder
	fmt.Fprintf(&output, "# SignalForge Golden Investor Dossier\n\n")
	fmt.Fprintf(&output, "**As of:** %s  \n", report.AsOf.Format("2006-01-02 15:04 UTC"))
	fmt.Fprintf(&output, "**Local model:** `%s`  \n", report.Model)
	fmt.Fprintf(&output, "**Question:** %s\n\n", report.Question)
	if report.Result.Failure != nil {
		fmt.Fprintf(&output, "## Visible Failure\n\n`%s`: %s\n", report.Result.Failure.FailureCode, report.Result.Failure.Message)
		return output.String()
	}
	if report.Result.Answer == nil {
		output.WriteString("## Visible Failure\n\nNo answer was released.\n")
		return output.String()
	}
	for _, section := range report.Result.Answer.Sections {
		fmt.Fprintf(&output, "## %s\n\n%s\n\n", section.Title, section.Content)
		if len(section.EvidenceRefs) > 0 {
			fmt.Fprintf(&output, "Evidence: `%s`\n\n", strings.Join(section.EvidenceRefs, "`, `"))
		}
		if len(section.ReceiptRefs) > 0 {
			fmt.Fprintf(&output, "Calculation receipts: `%s`\n\n", strings.Join(section.ReceiptRefs, "`, `"))
		}
	}
	if len(report.Result.Answer.Assumptions) > 0 {
		output.WriteString("## Assumptions Register\n\n")
		for _, assumption := range report.Result.Answer.Assumptions {
			fmt.Fprintf(&output, "- %s\n", assumption)
		}
		output.WriteString("\n")
	}
	if len(report.Result.Answer.Limitations) > 0 {
		output.WriteString("## Limitations Register\n\n")
		for _, limitation := range report.Result.Answer.Limitations {
			fmt.Fprintf(&output, "- %s\n", limitation)
		}
		output.WriteString("\n")
	}
	output.WriteString("## Auditable Calculation Ledger\n\n")
	receipts := map[string]receiptSummary{}
	for _, packet := range report.Result.Packets {
		for _, receipt := range packet.CalculationReceipts {
			outputs := make([]string, 0, len(receipt.Outputs))
			for _, value := range receipt.Outputs {
				if strings.Contains(value.OutputID, "present_values.") || strings.Contains(value.OutputID, "scenario_matrix.") {
					continue
				}
				quantity := value.Quantity.Value + " " + value.Quantity.Unit
				if value.Quantity.Currency != "" {
					quantity += " " + value.Quantity.Currency
				}
				outputs = append(outputs, value.OutputID+"="+quantity)
			}
			receipts[receipt.ReceiptID] = receiptSummary{Operation: receipt.OperationID, Outputs: outputs, SHA: receipt.ReceiptSHA}
		}
	}
	ids := make([]string, 0, len(receipts))
	for id := range receipts {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	for _, id := range ids {
		receipt := receipts[id]
		fmt.Fprintf(&output, "- `%s` · `%s` · %s · SHA `%s`\n", id, receipt.Operation, strings.Join(receipt.Outputs, ", "), receipt.SHA)
	}
	if len(ids) == 0 {
		output.WriteString("- No calculation receipt was used by an approved specialist claim.\n")
	}
	fmt.Fprintf(&output, "\n## Runtime Evidence\n\n- End-to-end latency: %.2f ms\n- Local model calls: %d\n- Context specialists: %d\n- Independent critics: %d\n- Supported-claim coverage: %.2f%%\n- Maximum concurrent context specialists: %d\n",
		report.Metrics.DurationMS, report.Metrics.ModelCalls, report.Metrics.ContextPackets,
		report.Metrics.Critiques, report.Metrics.EvidenceCoverage*100, report.Metrics.MaxConcurrentContext)
	return output.String()
}

type receiptSummary struct {
	Operation string
	Outputs   []string
	SHA       string
}
