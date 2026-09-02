package financialintelligence

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/metricregistry"
	"github.com/rvbernucci/signalforge/internal/roles"
)

func TestSpecialistPacketsAreBoundedAndCriticUsesIndependentReceipts(t *testing.T) {
	packet, err := Build(packetOptions(metricregistry.ProfileOperatingCompany), []contracts.CalculationReceipt{receiptFixture(t)})
	if err != nil {
		t.Fatal(err)
	}
	set, err := BuildSpecialistPackets(packet, map[string]string{roles.EvidenceCritic: "Independently verify receipts and source pointers."})
	if err != nil {
		t.Fatal(err)
	}
	if len(set.Packets) != 6 {
		t.Fatalf("expected six financial specialist packets, got %d", len(set.Packets))
	}
	var critic *SpecialistPacket
	for index := range set.Packets {
		if set.Packets[index].RoleID == roles.EvidenceCritic {
			critic = &set.Packets[index]
		}
	}
	if critic == nil || len(critic.ReceiptRefs) != 1 || len(critic.Evidence) == 0 {
		t.Fatalf("critic does not have independent proof material: %+v", critic)
	}
	encoded, err := json.Marshal(set)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(encoded), `"value":`) || strings.Contains(string(encoded), `"normalized_inputs":`) {
		t.Fatalf("specialist packet leaked authoritative numerical material: %s", encoded)
	}
	drawer, err := BuildProofDrawer(set)
	if err != nil || len(drawer.Records) < 2 {
		t.Fatalf("proof drawer is incomplete: %+v, %v", drawer, err)
	}
}

func TestAvailabilityStatesFailClosed(t *testing.T) {
	set := SpecialistPacketSet{
		SchemaVersion: SpecialistPacketSchemaV1, RunID: "run", AsOf: packetOptions(metricregistry.ProfileOperatingCompany).AsOf,
	}
	for roleID := range financialSpecialistRoles {
		set.Packets = append(set.Packets, SpecialistPacket{
			SchemaVersion: SpecialistPacketSchemaV1, PacketID: "packet:" + roleID,
			RunID: "run", RoleID: roleID, Objective: "bounded", AsOf: set.AsOf,
			Availability: AvailabilityNotApplicable, Limitations: []string{"not applicable"},
		})
	}
	if err := ValidateSpecialistPacketSet(set); err != nil {
		t.Fatal(err)
	}
	set.Packets[0].Availability = AvailabilityMissingData
	set.Packets[0].MissingEvidence = nil
	if err := ValidateSpecialistPacketSet(set); err == nil {
		t.Fatal("missing-data state without missing evidence must fail")
	}
}

func TestSpecialistPacketRejectsAmbiguousReceiptReferences(t *testing.T) {
	packet, err := Build(packetOptions(metricregistry.ProfileOperatingCompany), []contracts.CalculationReceipt{receiptFixture(t)})
	if err != nil {
		t.Fatal(err)
	}
	set, err := BuildSpecialistPackets(packet, nil)
	if err != nil {
		t.Fatal(err)
	}
	var target *SpecialistPacket
	for index := range set.Packets {
		if len(set.Packets[index].ReceiptRefs) > 0 {
			target = &set.Packets[index]
			break
		}
	}
	if target == nil {
		t.Fatal("fixture did not produce a receipt-bearing specialist packet")
	}
	target.ReceiptRefs = append(target.ReceiptRefs, target.ReceiptRefs[0])
	if err := ValidateSpecialistPacketSet(set); err == nil {
		t.Fatal("duplicate receipt references must fail closed")
	}

	set, err = BuildSpecialistPackets(packet, nil)
	if err != nil {
		t.Fatal(err)
	}
	for index := range set.Packets {
		if len(set.Packets[index].ReceiptRefs) > 0 {
			set.Packets[index].ReceiptRefs[0].Status = contracts.ReceiptStatus("unknown")
			break
		}
	}
	if err := ValidateSpecialistPacketSet(set); err == nil {
		t.Fatal("unknown receipt status must fail closed")
	}
}
