package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"

	"github.com/rvbernucci/signalforge/internal/release"
)

func main() {
	root := flag.String("root", ".", "repository root")
	claimsPath := flag.String("claims", "evidence/public-claims.json", "public claim registry")
	checklistPath := flag.String("checklist", "", "optional final release checklist")
	refreshEvidence := flag.Bool(
		"refresh-evidence",
		false,
		"recompute hashes for evidence paths already declared in the public claim registry",
	)
	flag.Parse()

	claims, err := release.ReadClaims(*claimsPath)
	if err != nil {
		fatal(err)
	}
	if *refreshEvidence {
		claims, err = release.RefreshClaimEvidence(*root, claims)
		if err != nil {
			fatal(err)
		}
		if err := writeClaims(*claimsPath, claims); err != nil {
			fatal(err)
		}
	}
	problems := release.CheckClaims(*root, claims)
	if *checklistPath != "" {
		checklist, err := release.ReadChecklist(*checklistPath)
		if err != nil {
			fatal(err)
		}
		problems = append(problems, release.CheckRelease(checklist)...)
	}
	if len(problems) > 0 {
		for _, problem := range problems {
			fmt.Fprintln(os.Stderr, problem)
		}
		os.Exit(1)
	}
	fmt.Println("release evidence checks passed")
}

func writeClaims(path string, claims release.ClaimRegistry) error {
	payload, err := json.MarshalIndent(claims, "", "  ")
	if err != nil {
		return err
	}
	payload = append(payload, '\n')
	directory := filepath.Dir(path)
	temporary, err := os.CreateTemp(directory, ".public-claims-*")
	if err != nil {
		return err
	}
	temporaryPath := temporary.Name()
	defer os.Remove(temporaryPath)
	if _, err := temporary.Write(payload); err != nil {
		temporary.Close()
		return err
	}
	if err := temporary.Chmod(0o644); err != nil {
		temporary.Close()
		return err
	}
	if err := temporary.Close(); err != nil {
		return err
	}
	return os.Rename(temporaryPath, path)
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, err)
	os.Exit(1)
}
