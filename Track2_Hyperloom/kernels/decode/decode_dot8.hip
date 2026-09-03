// int4 decode GEMV via the NATIVE 8-wide int4 dot: v_dot8_i32_iu4 (1 instr / 8 values).
#include "decode_common.hpp"

__global__ void gemv_dot8(const uint32_t* __restrict__ w, const uint32_t* __restrict__ a,
                          int32_t* __restrict__ o, int n, int kw){
  int row = blockIdx.x*blockDim.x + threadIdx.x;
  if(row>=n) return;
  const uint32_t* wr = w + (size_t)row*kw;
  int acc=0;
  for(int k=0;k<kw;k++)
    acc = __builtin_amdgcn_sudot8(true, (int)wr[k], true, (int)a[k], acc, false); // 8x int4 -> i32
  o[row]=acc;
}
void gemv_gpu(const uint32_t* d_w,const uint32_t* d_a,int32_t* d_out,int n,int kw){
  int t=256, b=(n+t-1)/t; gemv_dot8<<<b,t>>>(d_w,d_a,d_out,n,kw);
}
const char* KERNEL_NAME(){ return "dot8_iu4  v_dot8_i32_iu4"; }
