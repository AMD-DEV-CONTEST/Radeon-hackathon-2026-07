package productscope

import (
	"testing"
	"time"

	"github.com/rvbernucci/signalforge/internal/contracts"
)

func TestBuildActivationMatrixDoesNotOverPromoteCoverage(t *testing.T) {
	now := time.Date(2026, 7, 24, 12, 0, 0, 0, time.UTC)
	report := CoverageReport{
		SchemaVersion: "coverage/v1", UniverseID: UniverseID, GeneratedAt: now,
		CompanyCount: 20, MetricCount: 2,
	}
	for _, company := range Companies() {
		report.Observations = append(report.Observations, CompanyCoverage{
			CIK: company.CompanyID[len("sec-cik:"):], CompanyID: company.CompanyID,
			DisplayName: company.DisplayName, HTTPStatus: 200,
			Metrics: []MetricCoverage{
				{MetricID: "financial.margin", MetricVersion: "1.0.0", Status: "covered"},
				{MetricID: "valuation.peer_multiple", MetricVersion: "1.0.0", Status: "not_xbrl_bound"},
			},
		})
	}
	matrix, err := BuildActivationMatrix(report, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
	if err != nil {
		t.Fatal(err)
	}
	if len(matrix.Profiles) != 20 || matrix.Summary.ActivationStates[string(contracts.ActivationDataReady)] != 20 ||
		matrix.Summary.ResearchReadyCompanies != 0 || matrix.Summary.EnabledPeerLanes != 0 {
		t.Fatalf("coverage was over-promoted: %+v", matrix.Summary)
	}
	for _, lane := range matrix.PeerLanes {
		if lane.Enabled {
			t.Fatalf("unevaluated peer lane %q was enabled", lane.LaneID)
		}
	}
}

func TestBuildActivationMatrixRejectsMissingIssuer(t *testing.T) {
	now := time.Date(2026, 7, 24, 12, 0, 0, 0, time.UTC)
	report := CoverageReport{UniverseID: UniverseID, GeneratedAt: now, CompanyCount: 20, MetricCount: 1}
	for _, company := range Companies()[:19] {
		report.Observations = append(report.Observations, CompanyCoverage{
			CIK: company.CompanyID[len("sec-cik:"):], CompanyID: company.CompanyID,
			DisplayName: company.DisplayName, HTTPStatus: 200,
			Metrics: []MetricCoverage{{MetricID: "financial.margin", Status: "covered"}},
		})
	}
	if _, err := BuildActivationMatrix(report, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"); err == nil {
		t.Fatal("incomplete universe was accepted")
	}
}
