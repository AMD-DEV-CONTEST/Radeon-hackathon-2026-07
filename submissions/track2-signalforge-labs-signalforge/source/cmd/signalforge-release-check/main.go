package main

import (
	"flag"
	"fmt"
	"os"

	"github.com/rvbernucci/signalforge/internal/release"
)

func main() {
	root := flag.String("root", ".", "repository root")
	claimsPath := flag.String("claims", "evidence/public-claims.json", "public claim registry")
	checklistPath := flag.String("checklist", "", "optional final release checklist")
	flag.Parse()

	claims, err := release.ReadClaims(*claimsPath)
	if err != nil {
		fatal(err)
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

func fatal(err error) {
	fmt.Fprintln(os.Stderr, err)
	os.Exit(1)
}
