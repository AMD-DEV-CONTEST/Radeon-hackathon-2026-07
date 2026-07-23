package native

import "testing"

func TestGPUAddRealHandVerified(t *testing.T) {
	a := []float32{1, 2, 3, 4}
	b := []float32{10, 20, 30, 40}

	result, err := GPUAdd(a, b)
	if err != nil {
		t.Fatalf("GPUAdd failed: %v", err)
	}

	want := []float32{11, 22, 33, 44}
	if len(result) != len(want) {
		t.Fatalf("GPUAdd returned %d elements, want %d", len(result), len(want))
	}
	for i := range want {
		if result[i] != want[i] {
			t.Errorf("index %d: expected %v, got %v", i, want[i], result[i])
		}
	}
	t.Logf("Real GPU add result: %v", result)
}

func TestGPUMatMulRealHandVerified(t *testing.T) {
	// 2x2 identity-like case, hand-verifiable:
	// [1 2]   [1 0]   [1 2]
	// [3 4] x [0 1] = [3 4]
	a := []float64{1, 2, 3, 4}
	identity := []float64{1, 0, 0, 1}

	result, err := GPUMatMul(a, identity, 2, 2, 2)
	if err != nil {
		t.Fatalf("GPUMatMul failed: %v", err)
	}

	want := []float64{1, 2, 3, 4}
	if len(result) != len(want) {
		t.Fatalf("GPUMatMul returned %d elements, want %d", len(result), len(want))
	}
	for i := range want {
		if result[i] != want[i] {
			t.Errorf("index %d: expected %v, got %v", i, want[i], result[i])
		}
	}
	t.Logf("Real GPU matmul result: %v", result)
}
