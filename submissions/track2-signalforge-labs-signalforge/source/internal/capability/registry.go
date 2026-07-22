package capability

import (
	"errors"
	"fmt"
	"regexp"
	"sort"
)

var operationIDPattern = regexp.MustCompile(`^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$`)

type Operation struct {
	ID                 string   `json:"operation_id"`
	Engine             string   `json:"engine"`
	FormulaVersion     string   `json:"formula_version"`
	Description        string   `json:"description"`
	NumericalPolicy    string   `json:"numerical_policy"`
	RequiredInputs     []string `json:"required_inputs"`
	Outputs            []string `json:"outputs"`
	AllowedRoles       []string `json:"allowed_roles"`
	AssumptionsAllowed bool     `json:"assumptions_allowed"`
	InputSchema        string   `json:"input_schema"`
	OutputSchema       string   `json:"output_schema"`
	TimeoutMS          int      `json:"timeout_ms"`
	SideEffectClass    string   `json:"side_effect_class"`
}

type Registry struct {
	operations map[string]Operation
}

func NewRegistry(operations []Operation) (Registry, error) {
	registry := Registry{operations: make(map[string]Operation, len(operations))}
	for _, operation := range operations {
		if err := validateOperation(operation); err != nil {
			return Registry{}, err
		}
		if _, exists := registry.operations[operation.ID]; exists {
			return Registry{}, fmt.Errorf("duplicate operation %q", operation.ID)
		}
		registry.operations[operation.ID] = cloneOperation(operation)
	}
	return registry, nil
}

func (registry Registry) Get(operationID string) (Operation, bool) {
	operation, ok := registry.operations[operationID]
	return cloneOperation(operation), ok
}

func (registry Registry) Authorizes(role, operationID string) bool {
	operation, ok := registry.operations[operationID]
	if !ok {
		return false
	}
	for _, allowed := range operation.AllowedRoles {
		if allowed == role {
			return true
		}
	}
	return false
}

func (registry Registry) List() []Operation {
	ids := make([]string, 0, len(registry.operations))
	for id := range registry.operations {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	result := make([]Operation, 0, len(ids))
	for _, id := range ids {
		result = append(result, cloneOperation(registry.operations[id]))
	}
	return result
}

func validateOperation(operation Operation) error {
	if !operationIDPattern.MatchString(operation.ID) {
		return fmt.Errorf("invalid operation ID %q", operation.ID)
	}
	if operation.Engine == "" || operation.FormulaVersion == "" || operation.Description == "" || operation.NumericalPolicy == "" || operation.InputSchema == "" || operation.OutputSchema == "" {
		return errors.New("engine, formula_version, description, numerical_policy, and schemas are required")
	}
	if len(operation.RequiredInputs) == 0 || len(operation.Outputs) == 0 || len(operation.AllowedRoles) == 0 {
		return errors.New("inputs, outputs, and allowed_roles cannot be empty")
	}
	if operation.TimeoutMS <= 0 || operation.SideEffectClass != "none" {
		return errors.New("deterministic operations require a positive timeout and side_effect_class none")
	}
	return nil
}

func cloneOperation(operation Operation) Operation {
	operation.RequiredInputs = append([]string(nil), operation.RequiredInputs...)
	operation.Outputs = append([]string(nil), operation.Outputs...)
	operation.AllowedRoles = append([]string(nil), operation.AllowedRoles...)
	return operation
}
