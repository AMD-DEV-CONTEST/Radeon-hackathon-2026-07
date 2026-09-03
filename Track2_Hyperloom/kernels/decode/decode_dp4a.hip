// int4 decode GEMV via the dp4a route: unpack int4->int8, then v_dot4_i32_iu8 (2 instr / 8 values).
#include "decode_common.hpp"

// unpack one uint32 of 8 signed int4 -> two uint32, each 4 signed int8 (lo nibbles / hi nibbles)
__device__ inline void unpack8(uint32_t p, int& lo, int& hi){
  int b0=0,b1=0;
  #pragma unroll
  for(int i=0;i<4;i++){ int v=(p>>(4*i))&0xF; if(v>=8)v-=16; b0 |= (v&0xFF)<<(8*i); }
  #pragma unroll
  for(int i=0;i<4;i++){ int v=(p>>(4*(i+4)))&0xF; if(v>=8)v-=16; b1 |= (v&0xFF)<<(8*i); }
  lo=b0; hi=b1;
}
__global__ void gemv_dp4a(const uint32_t* __restrict__ w, const uint32_t* __restrict__ a,
                          int32_t* __restrict__ o, int n, int kw){
  int row = blockIdx.x*blockDim.x + threadIdx.x;
  if(row>=n) return;
  const uint32_t* wr = w + (size_t)row*kw;
  int acc=0;
  for(int k=0;k<kw;k++){
    int wlo,whi,alo,ahi; unpack8(wr[k],wlo,whi); unpack8(a[k],alo,ahi);
    acc = __builtin_amdgcn_sudot4(true, wlo, true, alo, acc, false); // 4x int8
    acc = __builtin_amdgcn_sudot4(true, whi, true, ahi, acc, false); // 4x int8
  }
  o[row]=acc;
}
void gemv_gpu(const uint32_t* d_w,const uint32_t* d_a,int32_t* d_out,int n,int kw){
  int t=256, b=(n+t-1)/t; gemv_dp4a<<<b,t>>>(d_w,d_a,d_out,n,kw);
}
const char* KERNEL_NAME(){ return "dp4a  unpack->v_dot4_i32_iu8"; }
