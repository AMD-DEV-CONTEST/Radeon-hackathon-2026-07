package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestValidateLoopbackListen(t *testing.T) {
	for _, address := range []string{"127.0.0.1:8080", "[::1]:8080", "localhost:8080"} {
		if err := validateLoopbackListen(address); err != nil {
			t.Fatalf("%s: %v", address, err)
		}
	}
	for _, address := range []string{"0.0.0.0:8080", "192.0.2.1:8080", "broken"} {
		if err := validateLoopbackListen(address); err == nil {
			t.Fatalf("expected %s to be rejected", address)
		}
	}
}

func TestValidateListenRequiresExplicitContainerBoundary(t *testing.T) {
	if err := validateListen("0.0.0.0:8080", true); err != nil {
		t.Fatal(err)
	}
	if err := validateListen("service-name:8080", true); err == nil {
		t.Fatal("DNS listener was accepted as an implicit trust boundary")
	}
}

func TestLoadAuditTokenIsFileOnlyAndExplicit(t *testing.T) {
	path := filepath.Join(t.TempDir(), "token")
	if err := os.WriteFile(path, []byte("operator-token\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := loadAuditToken(path, false); err == nil {
		t.Fatal("token file was accepted while capture was disabled")
	}
	if _, err := loadAuditToken("", true); err == nil {
		t.Fatal("capture was accepted without a token file")
	}
	token, err := loadAuditToken(path, true)
	if err != nil || token != "operator-token" {
		t.Fatalf("token = %q, err = %v", token, err)
	}
}

func TestOpenEventLogWritesSafeCollectorFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), "logs", "events.jsonl")
	writer, closeLog, err := openEventLog(path)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := writer.Write([]byte("{\"event\":\"test\"}\n")); err != nil {
		t.Fatal(err)
	}
	closeLog()
	payload, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if string(payload) != "{\"event\":\"test\"}\n" {
		t.Fatalf("payload = %q", payload)
	}
}
