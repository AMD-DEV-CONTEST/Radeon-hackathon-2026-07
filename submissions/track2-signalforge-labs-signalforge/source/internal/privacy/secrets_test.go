package privacy

import "testing"

func TestContainsSecretDetectsCredentialShapesWithoutBlockingOrdinaryResearch(t *testing.T) {
	for _, value := range []string{
		`{"authorization":"Bearer abcdefghijklmnopqrstuvwxyz"}`,
		`{"question":"api_key=super-secret-value"}`,
		`{"token":"hf_abcdefghijklmnopqrstuvwxyz"}`,
		`{"token":"sk-abcdefghijklmnopqrstuvwxyz"}`,
	} {
		if !ContainsSecret([]byte(value)) {
			t.Fatalf("secret shape not detected: %s", value)
		}
	}
	for _, value := range []string{
		`{"question":"How should an investor think about API key rotation?"}`,
		`{"section":"Microsoft revenue was rendered from a deterministic receipt."}`,
	} {
		if ContainsSecret([]byte(value)) {
			t.Fatalf("ordinary research text was blocked: %s", value)
		}
	}
}
