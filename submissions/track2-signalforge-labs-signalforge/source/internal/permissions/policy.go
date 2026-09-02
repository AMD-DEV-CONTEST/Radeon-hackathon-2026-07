package permissions

import "errors"

type Authority string
type Operation string

const (
	AuthoritySystem Authority = "system"
	AuthorityUser   Authority = "user"
	AuthorityModel  Authority = "model"

	SourceRead    Operation = "source.read"
	Compute       Operation = "calculation.execute"
	CaseRead      Operation = "case.read"
	CaseSave      Operation = "case.save"
	CaseExport    Operation = "case.export"
	CaseDelete    Operation = "case.delete"
	ExternalWrite Operation = "external.write"
)

var ErrDenied = errors.New("operation denied by local permission policy")

// Authorize keeps model tools read-only and reserves durable mutations for an
// explicit user action represented by the local workspace request.
func Authorize(authority Authority, operation Operation) error {
	switch operation {
	case SourceRead, Compute:
		if authority == AuthoritySystem || authority == AuthorityUser || authority == AuthorityModel {
			return nil
		}
	case CaseRead:
		if authority == AuthoritySystem || authority == AuthorityUser {
			return nil
		}
	case CaseSave, CaseExport, CaseDelete:
		if authority == AuthorityUser {
			return nil
		}
	case ExternalWrite:
		return ErrDenied
	}
	return ErrDenied
}
