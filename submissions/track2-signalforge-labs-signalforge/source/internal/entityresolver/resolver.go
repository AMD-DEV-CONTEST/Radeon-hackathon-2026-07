package entityresolver

import (
	"sort"
	"strings"
	"unicode"
)

type Security struct {
	SecurityID string `json:"security_id"`
	Ticker     string `json:"ticker"`
	Exchange   string `json:"exchange"`
	Primary    bool   `json:"primary"`
	ValidFrom  string `json:"valid_from,omitempty"`
	ValidTo    string `json:"valid_to,omitempty"`
}

type Issuer struct {
	CompanyID    string     `json:"company_id"`
	CIK          string     `json:"cik"`
	DisplayName  string     `json:"display_name"`
	NameAliases  []string   `json:"name_aliases"`
	Securities   []Security `json:"securities"`
	FiscalPolicy string     `json:"fiscal_policy"`
}

type Resolution struct {
	Mention      string `json:"mention"`
	MatchKind    string `json:"match_kind"`
	CompanyID    string `json:"company_id"`
	SecurityID   string `json:"security_id,omitempty"`
	Ticker       string `json:"ticker,omitempty"`
	Resolved     bool   `json:"resolved"`
	NeedsReview  bool   `json:"needs_review"`
	CanonicalKey string `json:"canonical_key"`
}

type Registry struct {
	issuers    []Issuer
	exactNames map[string][]int
	tickers    map[string][]securityIndex
}

type securityIndex struct {
	issuerIndex   int
	securityIndex int
}

func DefaultRegistry() Registry {
	return NewRegistry(defaultIssuers())
}

func NewRegistry(issuers []Issuer) Registry {
	result := Registry{
		issuers:    append([]Issuer(nil), issuers...),
		exactNames: map[string][]int{},
		tickers:    map[string][]securityIndex{},
	}
	for issuerIndex, issuer := range result.issuers {
		for _, name := range append([]string{issuer.DisplayName}, issuer.NameAliases...) {
			key := normalize(name)
			result.exactNames[key] = append(result.exactNames[key], issuerIndex)
		}
		for securityPosition, security := range issuer.Securities {
			key := strings.ToUpper(strings.TrimSpace(security.Ticker))
			result.tickers[key] = append(result.tickers[key], securityIndex{
				issuerIndex: issuerIndex, securityIndex: securityPosition,
			})
		}
	}
	return result
}

func (registry Registry) ResolveMention(mention string) Resolution {
	trimmed := strings.TrimSpace(mention)
	if trimmed == "" {
		return Resolution{Mention: mention}
	}
	tickerKey := strings.ToUpper(trimmed)
	if matches := registry.tickers[tickerKey]; len(matches) == 1 {
		issuer := registry.issuers[matches[0].issuerIndex]
		security := issuer.Securities[matches[0].securityIndex]
		return Resolution{
			Mention: trimmed, MatchKind: "ticker_exact", CompanyID: issuer.CompanyID,
			SecurityID: security.SecurityID, Ticker: security.Ticker, Resolved: true,
			CanonicalKey: issuer.CompanyID + "/" + security.SecurityID,
		}
	} else if len(matches) > 1 {
		return Resolution{Mention: trimmed, MatchKind: "ticker_collision", NeedsReview: true}
	}
	nameKey := normalize(trimmed)
	if matches := registry.exactNames[nameKey]; len(matches) == 1 {
		issuer := registry.issuers[matches[0]]
		return Resolution{
			Mention: trimmed, MatchKind: "name_exact", CompanyID: issuer.CompanyID,
			Resolved: true, CanonicalKey: issuer.CompanyID,
		}
	} else if len(matches) > 1 {
		return Resolution{Mention: trimmed, MatchKind: "name_collision", NeedsReview: true}
	}
	if len([]rune(nameKey)) < 5 {
		return Resolution{Mention: trimmed, MatchKind: "unresolved"}
	}
	candidates := []int{}
	for candidate, matches := range registry.exactNames {
		if boundedDistance(nameKey, candidate, 1) <= 1 {
			candidates = append(candidates, matches...)
		}
	}
	candidates = uniqueInts(candidates)
	if len(candidates) == 1 {
		issuer := registry.issuers[candidates[0]]
		return Resolution{
			Mention: trimmed, MatchKind: "name_fuzzy_bounded", CompanyID: issuer.CompanyID,
			Resolved: true, NeedsReview: true, CanonicalKey: issuer.CompanyID,
		}
	}
	if len(candidates) > 1 {
		return Resolution{Mention: trimmed, MatchKind: "fuzzy_collision", NeedsReview: true}
	}
	return Resolution{Mention: trimmed, MatchKind: "unresolved"}
}

func (registry Registry) ResolveText(text string) []Resolution {
	lower := strings.ToLower(text)
	matches := []Resolution{}
	occupied := map[string]bool{}
	nameCandidates := []struct {
		mention string
		length  int
	}{}
	for _, issuer := range registry.issuers {
		for _, name := range append([]string{issuer.DisplayName}, issuer.NameAliases...) {
			if strings.Contains(lower, strings.ToLower(name)) {
				nameCandidates = append(nameCandidates, struct {
					mention string
					length  int
				}{mention: name, length: len([]rune(name))})
			}
		}
	}
	sort.Slice(nameCandidates, func(i, j int) bool {
		if nameCandidates[i].length != nameCandidates[j].length {
			return nameCandidates[i].length > nameCandidates[j].length
		}
		return nameCandidates[i].mention < nameCandidates[j].mention
	})
	for _, candidate := range nameCandidates {
		resolution := registry.ResolveMention(candidate.mention)
		if resolution.Resolved && !occupied[resolution.CanonicalKey] {
			matches = append(matches, resolution)
			occupied[resolution.CanonicalKey] = true
		}
	}
	for _, token := range strings.FieldsFunc(text, func(char rune) bool {
		return !unicode.IsLetter(char) && !unicode.IsDigit(char)
	}) {
		resolution := registry.ResolveMention(token)
		if resolution.MatchKind == "ticker_exact" && !occupied[resolution.CanonicalKey] {
			resolution.Mention = token
			matches = append(matches, resolution)
			occupied[resolution.CanonicalKey] = true
		}
	}
	sort.SliceStable(matches, func(i, j int) bool {
		return strings.ToLower(matches[i].Mention) < strings.ToLower(matches[j].Mention)
	})
	return matches
}

func (registry Registry) Issuers() []Issuer {
	return append([]Issuer(nil), registry.issuers...)
}

func normalize(value string) string {
	return strings.Join(strings.Fields(strings.ToLower(value)), " ")
}

func boundedDistance(left, right string, maximum int) int {
	a, b := []rune(left), []rune(right)
	if difference(len(a), len(b)) > maximum {
		return maximum + 1
	}
	previous := make([]int, len(b)+1)
	for index := range previous {
		previous[index] = index
	}
	for i := 1; i <= len(a); i++ {
		current := make([]int, len(b)+1)
		current[0] = i
		rowMinimum := current[0]
		for j := 1; j <= len(b); j++ {
			cost := 0
			if a[i-1] != b[j-1] {
				cost = 1
			}
			current[j] = minimum(previous[j]+1, current[j-1]+1, previous[j-1]+cost)
			if current[j] < rowMinimum {
				rowMinimum = current[j]
			}
		}
		if rowMinimum > maximum {
			return maximum + 1
		}
		previous = current
	}
	return previous[len(b)]
}

func difference(left, right int) int {
	if left > right {
		return left - right
	}
	return right - left
}

func minimum(values ...int) int {
	result := values[0]
	for _, value := range values[1:] {
		if value < result {
			result = value
		}
	}
	return result
}

func uniqueInts(values []int) []int {
	seen := map[int]bool{}
	result := []int{}
	for _, value := range values {
		if !seen[value] {
			result = append(result, value)
			seen[value] = true
		}
	}
	return result
}

func defaultIssuers() []Issuer {
	security := func(ticker string, primary bool) Security {
		return Security{
			SecurityID: "us-equity:" + ticker, Ticker: ticker, Exchange: "NASDAQ",
			Primary: primary,
		}
	}
	issuer := func(cik, name, ticker string, aliases ...string) Issuer {
		return Issuer{
			CompanyID: "sec-cik:" + cik, CIK: cik, DisplayName: name, NameAliases: aliases,
			Securities: []Security{security(ticker, true)}, FiscalPolicy: "issuer_reported",
		}
	}
	result := []Issuer{
		issuer("0000320193", "Apple", "AAPL", "Apple Inc."),
		issuer("0000789019", "Microsoft", "MSFT", "Microsoft Corporation"),
		issuer("0001018724", "Amazon", "AMZN", "Amazon.com", "Amazon.com Inc."),
		issuer("0001326801", "Meta Platforms", "META", "Meta", "Facebook"),
		issuer("0001045810", "NVIDIA", "NVDA", "Nvidia Corporation"),
		issuer("0000002488", "Advanced Micro Devices", "AMD", "AMD"),
		issuer("0001730168", "Broadcom", "AVGO", "Broadcom Inc."),
		issuer("0000050863", "Intel", "INTC", "Intel Corporation"),
		issuer("0000804328", "Qualcomm", "QCOM", "Qualcomm Incorporated"),
		issuer("0000723125", "Micron Technology", "MU", "Micron"),
		issuer("0000097476", "Texas Instruments", "TXN"),
		issuer("0000006951", "Applied Materials", "AMAT"),
		issuer("0001341439", "Oracle", "ORCL", "Oracle Corporation"),
		issuer("0001108524", "Salesforce", "CRM", "Salesforce Inc."),
		issuer("0000796343", "Adobe", "ADBE", "Adobe Inc."),
		issuer("0001373715", "ServiceNow", "NOW"),
		issuer("0000858877", "Cisco Systems", "CSCO", "Cisco"),
		issuer("0000051143", "IBM", "IBM", "International Business Machines"),
		issuer("0001596532", "Arista Networks", "ANET", "Arista"),
	}
	alphabet := issuer("0001652044", "Alphabet", "GOOGL", "Alphabet Inc.", "Google")
	alphabet.Securities = append(alphabet.Securities, security("GOOG", false))
	result = append(result, alphabet)
	return result
}
