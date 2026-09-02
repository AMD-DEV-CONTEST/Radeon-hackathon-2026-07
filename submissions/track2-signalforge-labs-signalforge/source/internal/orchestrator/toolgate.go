package orchestrator

import (
	"errors"
	"fmt"

	"github.com/rvbernucci/signalforge/internal/capability"
	"github.com/rvbernucci/signalforge/internal/roles"
)

type ToolGate struct {
	Capabilities capability.Registry
	Roles        roles.Registry
}

func (gate ToolGate) Authorize(roleID, operationID string) (capability.Operation, error) {
	role, ok := gate.Roles.Get(roleID)
	if !ok {
		return capability.Operation{}, fmt.Errorf("unknown role %q", roleID)
	}
	if !contains(role.AllowedTools, "engine.execute") {
		return capability.Operation{}, errors.New("role cannot invoke the deterministic engine")
	}
	operation, ok := gate.Capabilities.Get(operationID)
	if !ok {
		return capability.Operation{}, errors.New("operation is not registered")
	}
	if !gate.Capabilities.Authorizes(roleID, operationID) {
		return capability.Operation{}, errors.New("operation is not authorized for role")
	}
	if operation.SideEffectClass != "none" || operation.TimeoutMS <= 0 || operation.InputSchema == "" || operation.OutputSchema == "" {
		return capability.Operation{}, errors.New("operation metadata is unsafe")
	}
	return operation, nil
}

func contains(values []string, target string) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}
