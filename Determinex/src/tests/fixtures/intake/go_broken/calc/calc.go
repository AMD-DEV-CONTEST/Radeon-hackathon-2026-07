// Intentionally broken — fixture for CODEBASE_EXPLORER_SMOKE_LOCK_001.

package calc

// Add intentionally returns a string from a signature declared to return int.
// `go build` will reject with "cannot use \"oops\" (untyped string constant)
// as int value in return statement".
func Add(a int, b int) int {
	return "oops"
}

func Multiply(a int, b int) int {
	return a * b
}
