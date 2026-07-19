#include <hip/hip_runtime.h>

// Kernel deliberadamente minúsculo e barato: seu único propósito é manter a
// GPU com alguma atividade real (não um no-op vazio, que o driver poderia
// otimizar/descartar) durante os intervalos ociosos entre rajadas de
// inferência, evitando que o gerenciador de energia (DPM) derrube o
// clock/voltagem para o mínimo e precise fazer uma transição abrupta de volta no
// próximo passo de decodificação — é essa transição brusca que causa
// stuttering/TDR quando alterna rápido demais entre ocioso e 100%.
extern "C" __global__ void keepalive_kernel(float* __restrict__ buf) {
    int idx = threadIdx.x;
    buf[idx] = buf[idx] * 1.0000001f + 0.0000001f;
}
