package producteval

import (
	"testing"

	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/golden"
	"github.com/rvbernucci/signalforge/internal/orchestrator"
	"github.com/rvbernucci/signalforge/internal/productscope"
)

func TestStandaloneScoreRequiresReceiptsCriticsAndVisibleAbstention(t *testing.T) {
	report := golden.Report{
		Request: contracts.ResearchRequest{AuthorityState: "data_ready"},
		Result: orchestrator.Result{
			Answer: &contracts.FinalAnswer{
				Limitations: []string{"Market price authority is unavailable."},
			},
			Packets: []contracts.ContextPacket{{
				CalculationReceipts: []contracts.CalculationReceipt{{
					OperationID: "financial.operating_margin",
				}},
			}},
		},
		Metrics: golden.Metrics{Claims: 2, SupportedClaims: 2},
		Acceptance: golden.Acceptance{
			RequiredSectionsReady: true,
			BothCriticsApproved:   true,
		},
	}
	result := ScoreStandaloneCase(productscope.StandaloneJourneyCase{
		JourneyID: "MSFT-fundamentals", CompanyID: "sec-cik:0000789019",
		PrimaryTicker: "MSFT", QuestionID: "fundamentals",
		ExpectedReceipts:    []string{"financial.operating_margin"},
		ExpectedAbstentions: []string{"valuation.fcff_dcf"},
	}, report, false)
	if !result.ContractPassed {
		t.Fatalf("result = %+v", result)
	}
	if result.Report != nil {
		t.Fatal("private report was retained when disabled")
	}
}

func TestStandaloneScoreRejectsAnUnexpectedReleasedReceipt(t *testing.T) {
	report := golden.Report{
		Request: contracts.ResearchRequest{AuthorityState: "data_ready"},
		Result: orchestrator.Result{
			Answer: &contracts.FinalAnswer{Limitations: []string{"bounded"}},
			Packets: []contracts.ContextPacket{{
				CalculationReceipts: []contracts.CalculationReceipt{{
					OperationID: "valuation.fcff_dcf",
				}},
			}},
		},
		Metrics: golden.Metrics{},
		Acceptance: golden.Acceptance{
			RequiredSectionsReady: true,
			BothCriticsApproved:   true,
		},
	}
	result := ScoreStandaloneCase(productscope.StandaloneJourneyCase{
		JourneyID: "MSFT-valuation", CompanyID: "sec-cik:0000789019",
		PrimaryTicker: "MSFT", QuestionID: "valuation",
		ExpectedAbstentions: []string{"valuation.fcff_dcf"},
	}, report, false)
	if result.ExpectedAbstentionsPassed || result.ContractPassed {
		t.Fatalf("unexpected receipt escaped abstention gate: %+v", result)
	}
}

func TestPeerScoreRequiresAuthorityBoundaryAndWithholdsUnavailableMetrics(t *testing.T) {
	report := golden.Report{
		Request: contracts.ResearchRequest{
			AuthorityState: "limited",
			AuthorityRefs: []string{
				"company-profile-sha256:left",
				"company-profile-sha256:right",
				"comparability-receipt-sha256:margin",
			},
		},
		Result: orchestrator.Result{
			Answer: &contracts.FinalAnswer{
				Sections: []contracts.AnswerSection{{
					SectionType: "comparison",
					Content:     "The comparison is bounded by fiscal-period caveats.",
				}},
				Limitations: []string{"Cash conversion remains unavailable."},
			},
			Packets: []contracts.ContextPacket{{
				NumericalContext: &contracts.NumericalContext{
					Variables: []contracts.NumericalVariable{{
						MetricID: "financial.operating_margin.margin",
					}},
				},
			}},
		},
		Metrics: golden.Metrics{Claims: 2, SupportedClaims: 2},
		Acceptance: golden.Acceptance{
			RequiredSectionsReady: true,
			BothCriticsApproved:   true,
		},
	}
	result := ScorePeerCase(productscope.PeerJourneyCase{
		JourneyID: "left-right-boundary", LaneID: "left-right",
		CompanyIDs: []string{"left", "right"}, QuestionID: "boundary",
		ExpectedMetrics: map[string]string{
			"financial.operating_margin": "comparable_with_caveat",
			"financial.cash_conversion":  "unavailable",
		},
	}, report, false)
	if !result.ContractPassed {
		t.Fatalf("peer result = %+v", result)
	}
}

func TestPeerScoreRejectsUnavailableMetricInNumericalContext(t *testing.T) {
	report := golden.Report{
		Request: contracts.ResearchRequest{
			AuthorityState: "limited",
			AuthorityRefs:  []string{"comparability-receipt-sha256:margin"},
		},
		Result: orchestrator.Result{
			Answer: &contracts.FinalAnswer{
				Sections:    []contracts.AnswerSection{{Content: "Fiscal caveats apply."}},
				Limitations: []string{"The comparison is bounded."},
			},
			Packets: []contracts.ContextPacket{{
				NumericalContext: &contracts.NumericalContext{
					Relations: []contracts.NumericalRelation{{
						MetricID: "financial.cash_conversion.cash_conversion",
					}},
				},
			}},
		},
		Acceptance: golden.Acceptance{
			RequiredSectionsReady: true,
			BothCriticsApproved:   true,
		},
	}
	result := ScorePeerCase(productscope.PeerJourneyCase{
		ExpectedMetrics: map[string]string{
			"financial.operating_margin": "comparable_with_caveat",
			"financial.cash_conversion":  "unavailable",
		},
	}, report, false)
	if result.UnavailableMetricsWithheld || result.ContractPassed {
		t.Fatalf("unavailable metric entered peer numerical context: %+v", result)
	}
}

func TestPeerScoreRejectsUnsupportedPairRanking(t *testing.T) {
	report := golden.Report{
		Request: contracts.ResearchRequest{
			AuthorityState: "limited",
			AuthorityRefs: []string{
				"company-profile-sha256:left",
				"company-profile-sha256:right",
				"comparability-receipt-sha256:margin",
			},
		},
		Result: orchestrator.Result{
			Answer: &contracts.FinalAnswer{
				Sections: []contracts.AnswerSection{{
					SectionType: "comparison",
					Content:     "Left is the better investment despite the bounded comparison.",
				}},
				Limitations: []string{"The comparison is bounded by fiscal-period caveats."},
			},
			Packets: []contracts.ContextPacket{{
				NumericalContext: &contracts.NumericalContext{
					Variables: []contracts.NumericalVariable{{
						MetricID: "financial.operating_margin.margin",
					}},
				},
			}},
		},
		Metrics: golden.Metrics{Claims: 1, SupportedClaims: 1},
		Acceptance: golden.Acceptance{
			RequiredSectionsReady: true,
			BothCriticsApproved:   true,
		},
	}
	result := ScorePeerCase(productscope.PeerJourneyCase{
		JourneyID: "left-right-ranking", LaneID: "left-right",
		CompanyIDs: []string{"left", "right"}, QuestionID: "ranking",
		ExpectedMetrics: map[string]string{
			"financial.operating_margin": "comparable_with_caveat",
		},
	}, report, false)
	if result.NoUnsupportedPairRanking || result.ContractPassed {
		t.Fatalf("unsupported ranking escaped the peer gate: %+v", result)
	}
}
