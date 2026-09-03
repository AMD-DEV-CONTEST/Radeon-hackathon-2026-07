// repro_harness.cu — grade an agent-written low-bit kernel against the golden.
// Harness owns inputs, reference and comparison. Agent supplies agent_kernel.cuh.
#include "quant_common.h"
#include <cstdio>
#include <cstdlib>
#include <cmath>
#include <vector>
#include "agent_kernel.cuh"

static std::vector<char> slurp(const char* p, size_t n) {
    FILE* f = fopen(p,"rb"); if(!f){fprintf(stderr,"missing %s\n",p);exit(2);}
    std::vector<char> v(n); if (fread(v.data(),1,n,f)!=n){fprintf(stderr,"short %s\n",p);exit(2);}
    fclose(f); return v;
}
int main() {
    const int N = 2048, Kb = 32;
    char pw[64],pa[64],po[64];
    snprintf(pw,sizeof pw,"golden_%s_w.bin",FMT_NAME);
    snprintf(pa,sizeof pa,"golden_%s_a.bin",FMT_NAME);
    snprintf(po,sizeof po,"golden_%s_o.bin",FMT_NAME);
    auto hW = slurp(pw,(size_t)N*Kb*sizeof(block_lowbit));
    auto hA = slurp(pa,(size_t)Kb*QK_LOWBIT*4);
    auto hG = slurp(po,(size_t)N*4);
    const float* golden = (const float*)hG.data();

    block_lowbit* dW; float *dA,*dO;
    hipMalloc(&dW,hW.size()); hipMalloc(&dA,hA.size()); hipMalloc(&dO,(size_t)N*4);
    hipMemcpy(dW,hW.data(),hW.size(),hipMemcpyHostToDevice);
    hipMemcpy(dA,hA.data(),hA.size(),hipMemcpyHostToDevice);
    agent_kernel<<<N,64,64*sizeof(float)>>>(dW,dA,dO,(int64_t)Kb);
    hipError_t e=hipDeviceSynchronize();
    if(e!=hipSuccess){printf("LAUNCH FAILED: %s\n",hipGetErrorString(e));return 1;}
    std::vector<float> got(N); hipMemcpy(got.data(),dO,(size_t)N*4,hipMemcpyDeviceToHost);
    // Error metric: max|a-b| normalised by the SCALE of the result, not per-row.
    //
    // A per-row relative error divides by |golden[i]|, so a row whose true value
    // happens to sit near zero turns ordinary fp32 rounding into a huge number.
    // That is not hypothetical: a verified-correct Q4_0 kernel scored 8.5e-03
    // because one row had |golden| = 4.9e-05, twenty-eight thousand times below
    // the mean, while its ABSOLUTE error was 4.2e-07 -- right at the average for
    // every other row. The metric was about to fail a correct kernel.
    //
    // What "these agree" actually means for a GEMV is that the worst absolute
    // disagreement is small compared to the typical magnitude of the output. So
    // that is what is measured. The worst per-row relative error is still printed
    // alongside, because it is informative -- it just must not be the gate.
    double mean_mag = 0.0;
    for (int i = 0; i < N; ++i) mean_mag += fabs((double)golden[i]);
    mean_mag /= N;

    double worst_abs = 0.0, worst_rel = 0.0; int bad = 0;
    for (int i = 0; i < N; ++i) {
        if (!std::isfinite(got[i])) { bad++; worst_abs = INFINITY; break; }
        const double d = fabs((double)got[i] - golden[i]);
        const double s = fabs((double)golden[i]);
        if (d > worst_abs) worst_abs = d;
        const double rel = s > 1e-6 ? d / s : d;
        if (rel > worst_rel) worst_rel = rel;
    }
    const double worst = (mean_mag > 0) ? worst_abs / mean_mag : worst_abs;
    printf("metric: max|a-b| / mean|golden|  (mean|golden|=%.6f)\n", mean_mag);
    printf("  max_abs_err=%.3e   worst_per_row_rel=%.3e (informational)\n",
           worst_abs, worst_rel);
    printf("fmt=%s rows=%d non_finite=%d max_rel_err=%.6e\n",FMT_NAME,N,bad,worst);
    printf("golden[0]=%.6f agent[0]=%.6f\n", golden[0], got[0]);
    return 0;
}
