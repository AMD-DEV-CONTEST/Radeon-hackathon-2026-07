// Shared harness for the int4-weight decode-GEMV comparison (dot8 vs dp4a).
// Same math both ways (out[n] = sum_k sext4(W[n][k]) * sext4(A[k])), same memory
// pattern, exact integer correctness vs CPU reference. Isolates the DOT instruction.
#include <hip/hip_runtime.h>
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <vector>

#ifndef N_ROWS
#define N_ROWS 14336      // T170 win shape (decode GEMV, M=1)
#endif
#ifndef K_DIM
#define K_DIM 4096
#endif
#define KW (K_DIM/8)      // uint32 words per row (8 signed int4 per 32-bit word)

// each kernel .hip provides these two:
void gemv_gpu(const uint32_t* d_w, const uint32_t* d_a, int32_t* d_out, int n, int kw);
const char* KERNEL_NAME();

static inline int sext4(uint32_t nib){ int v = nib & 0xF; return v>=8 ? v-16 : v; }
#define HIPCHECK(x) do{ hipError_t _hc=(x); if(_hc){printf("HIP err: %s\n",hipGetErrorString(_hc)); exit(2);} }while(0)

int main(){
  srand(1234);
  size_t wwords=(size_t)N_ROWS*KW;
  std::vector<uint32_t> h_w(wwords), h_a(KW);
  for(auto&x:h_w) x=((uint32_t)rand()<<1)^rand();
  for(auto&x:h_a) x=((uint32_t)rand()<<1)^rand();

  // CPU reference — exact signed-int4 dot products
  std::vector<int32_t> ref(N_ROWS,0);
  for(int n=0;n<N_ROWS;n++){
    int64_t acc=0;
    const uint32_t* wr=&h_w[(size_t)n*KW];
    for(int w=0;w<KW;w++){ uint32_t ww=wr[w], aw=h_a[w];
      for(int i=0;i<8;i++) acc += (int64_t)sext4(ww>>(4*i))*sext4(aw>>(4*i)); }
    ref[n]=(int32_t)acc;
  }

  uint32_t *d_w,*d_a; int32_t *d_out;
  HIPCHECK(hipMalloc(&d_w,wwords*4)); HIPCHECK(hipMalloc(&d_a,KW*4)); HIPCHECK(hipMalloc(&d_out,(size_t)N_ROWS*4));
  HIPCHECK(hipMemcpy(d_w,h_w.data(),wwords*4,hipMemcpyHostToDevice));
  HIPCHECK(hipMemcpy(d_a,h_a.data(),KW*4,hipMemcpyHostToDevice));

  // correctness
  gemv_gpu(d_w,d_a,d_out,N_ROWS,KW); HIPCHECK(hipDeviceSynchronize());
  std::vector<int32_t> out(N_ROWS);
  HIPCHECK(hipMemcpy(out.data(),d_out,(size_t)N_ROWS*4,hipMemcpyDeviceToHost));
  int bad=0; for(int n=0;n<N_ROWS;n++) if(out[n]!=ref[n]){ if(bad<5) printf("  mismatch n=%d gpu=%d ref=%d\n",n,out[n],ref[n]); bad++; }
  bool ok=(bad==0);

  // timing (median-ish via event over MEAS iters, after warmup)
  const int MEAS=300, WARM=30;
  for(int i=0;i<WARM;i++) gemv_gpu(d_w,d_a,d_out,N_ROWS,KW);
  HIPCHECK(hipDeviceSynchronize());
  hipEvent_t s,e; hipEventCreate(&s); hipEventCreate(&e);
  hipEventRecord(s); for(int i=0;i<MEAS;i++) gemv_gpu(d_w,d_a,d_out,N_ROWS,KW);
  hipEventRecord(e); HIPCHECK(hipEventSynchronize(e));
  float ms=0; hipEventElapsedTime(&ms,s,e); ms/=MEAS;
  double wbytes=(double)N_ROWS*K_DIM*0.5;     // int4 weights = 0.5 byte/elem
  double gbps=wbytes/1e9/(ms/1000.0);
  printf("[%s] N=%d K=%d  correctness=%s  time=%.5f ms  weight-BW=%.1f GB/s\n",
         KERNEL_NAME(),N_ROWS,K_DIM, ok?"PASS":"FAIL", ms, gbps);
  hipFree(d_w); hipFree(d_a); hipFree(d_out);
  return ok?0:1;
}
