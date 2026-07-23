package native

/*
#cgo CFLAGS: -I.
#cgo LDFLAGS: -L/home/clexious/harold-demo-AMD-Hackathon-2026/gospark-demo/native -L/opt/rocm-6.4.0/lib -lgospark_demo -lamdhip64 -lstdc++ -Wl,-rpath,/home/clexious/harold-demo-AMD-Hackathon-2026/gospark-demo/native:/opt/rocm-6.4.0/lib
#include "bridge.h"
*/
import "C"
import (
	"fmt"
	"unsafe"
)

// GPUAdd runs real element-wise addition on the GPU via the actual
// proven HIP kernel copied from GoSpark. Real float32 precision,
// matching the original kernel's own signature exactly.
func GPUAdd(a, b []float32) ([]float32, error) {
	if len(a) != len(b) {
		return nil, fmt.Errorf("gpu add: mismatched lengths %d vs %d", len(a), len(b))
	}
	n := len(a)
	result := make([]float32, n)

	status := C.gpu_add(
		(*C.float)(unsafe.Pointer(&a[0])),
		(*C.float)(unsafe.Pointer(&b[0])),
		(*C.float)(unsafe.Pointer(&result[0])),
		C.int(n),
	)
	if status != 0 {
		return nil, fmt.Errorf("gpu add: real HIP kernel returned failure status %d", status)
	}
	return result, nil
}

// GPUMatMul runs a real matrix multiplication on the GPU via the
// actual proven HIP kernel copied from GoSpark. a is m x n, b is n x p,
// result is m x p, all in real row-major flat layout.
func GPUMatMul(a, b []float64, m, n, p int) ([]float64, error) {
	if len(a) != m*n {
		return nil, fmt.Errorf("gpu matmul: a has %d elements, expected %d (m*n)", len(a), m*n)
	}
	if len(b) != n*p {
		return nil, fmt.Errorf("gpu matmul: b has %d elements, expected %d (n*p)", len(b), n*p)
	}
	result := make([]float64, m*p)

	status := C.gpu_matmul(
		(*C.double)(unsafe.Pointer(&a[0])),
		(*C.double)(unsafe.Pointer(&b[0])),
		(*C.double)(unsafe.Pointer(&result[0])),
		C.int(m), C.int(n), C.int(p),
	)
	if status != 0 {
		return nil, fmt.Errorf("gpu matmul: real HIP kernel returned failure status %d", status)
	}
	return result, nil
}

// GPUReLU runs real ReLU activation on the GPU via the actual proven
// HIP kernel copied from GoSpark.
func GPUReLU(input []float64) ([]float64, error) {
	n := len(input)
	result := make([]float64, n)

	status := C.gpu_relu(
		(*C.double)(unsafe.Pointer(&input[0])),
		(*C.double)(unsafe.Pointer(&result[0])),
		C.int(n),
	)
	if status != 0 {
		return nil, fmt.Errorf("gpu relu: real HIP kernel returned failure status %d", status)
	}
	return result, nil
}

// GPUSoftmax runs real, numerically-stable softmax on the GPU via the
// actual proven HIP kernel copied from GoSpark, one row at a time.
func GPUSoftmax(input []float64, rows, cols int) ([]float64, error) {
	if len(input) != rows*cols {
		return nil, fmt.Errorf("gpu softmax: input has %d elements, expected %d (rows*cols)", len(input), rows*cols)
	}
	result := make([]float64, rows*cols)

	status := C.gpu_softmax(
		(*C.double)(unsafe.Pointer(&input[0])),
		(*C.double)(unsafe.Pointer(&result[0])),
		C.int(rows), C.int(cols),
	)
	if status != 0 {
		return nil, fmt.Errorf("gpu softmax: real HIP kernel returned failure status %d", status)
	}
	return result, nil
}

// GPULayerNorm runs real layer normalization on the GPU via the actual
// proven HIP kernel copied from GoSpark, returning the normalized
// output plus xhat and stdInv (both needed for a real backward pass
// later, matching core/layernorm.go's own gradient formula).
func GPULayerNorm(x, gamma, beta []float64, rows, cols int, eps float64) (output, xhat, stdInv []float64, err error) {
	if len(x) != rows*cols {
		return nil, nil, nil, fmt.Errorf("gpu layernorm: x has %d elements, expected %d (rows*cols)", len(x), rows*cols)
	}
	if len(gamma) != cols || len(beta) != cols {
		return nil, nil, nil, fmt.Errorf("gpu layernorm: gamma/beta must have %d elements each", cols)
	}

	output = make([]float64, rows*cols)
	xhat = make([]float64, rows*cols)
	stdInv = make([]float64, rows)

	status := C.gpu_layernorm(
		(*C.double)(unsafe.Pointer(&x[0])),
		(*C.double)(unsafe.Pointer(&gamma[0])),
		(*C.double)(unsafe.Pointer(&beta[0])),
		(*C.double)(unsafe.Pointer(&output[0])),
		(*C.double)(unsafe.Pointer(&xhat[0])),
		(*C.double)(unsafe.Pointer(&stdInv[0])),
		C.int(rows), C.int(cols), C.double(eps),
	)
	if status != 0 {
		return nil, nil, nil, fmt.Errorf("gpu layernorm: real HIP kernel returned failure status %d", status)
	}
	return output, xhat, stdInv, nil
}
