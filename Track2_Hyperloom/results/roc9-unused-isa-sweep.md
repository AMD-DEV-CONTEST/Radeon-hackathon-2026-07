v_wmma_f32_16x16x16_f16            7860  fattn-mma-f16-instance-ncols1_8-ncols2_8:912 fattn-mma-f16-instance-ncols1_32-ncols2_2:912 fattn-mma-f16-instance-ncols1_16-ncols2_4:912 
v_wmma_f32_16x16x16_bf16           3072  mmf-instance-ncols_9:192 mmf-instance-ncols_8:192 mmf-instance-ncols_7:192 
v_wmma_f32_16x16x16_fp8            1532  mmq-instance-f8e4m3:864 mmq-instance-mxfp8:368 mul_mat_dense_fp8_mmq:168 
v_wmma_f32_16x16x16_bf8             368  mmq-instance-f8e5m2:368 
v_wmma_i32_16x16x16_iu8            7740  mmq-instance-q2_k:752 mmq:720 mmq-instance-q8_0:360 
v_wmma_i32_16x16x32_iu4              44  mul_mat_iu4_mmq:40 mul_mat_q2_0_wmma:2 mul_mat_iu4:1 
v_swmmac_f32_16x16x32_fp8           482  mul_mat_2of4_fp8_mmq:408 mul_mat_2of4_fp8:73 swmmac24_iu4_fixed:1 
v_swmmac_f32_16x16x32_f16             2  swmmac24_iu4_fixed:1 mul_mat_2of4_f16:1 
v_swmmac_i32_16x16x64_iu4             0   *** UNUSED (in HW, 0 uses) ***
v_dot8_i32_iu4                        4  mmvq_iu4:4 
v_dot4_i32_iu8                     8624  mmvq:7376 fattn-vec-instance-q8_0-q8_0:624 fattn-vec-instance-q4_0-q4_0:624 
v_dot4_f32_fp8                      110  mmvq:110 
v_dot2_f32_f16                   125666  fattn-tile-instance-dkq128-dv128:29568 fattn-tile-instance-dkq512-dv512:24576 fattn-tile-instance-dkq256-dv256:17152 
v_dot2_f32_bf16                       0   *** UNUSED (in HW, 0 uses) ***
v_cvt_pk_fp8                          3  quantize:2 mul_mat_q2_0_fp8route_mmq:1 
v_cvt_pk_bf8                          2  quantize:2 
v_cvt_sr_fp8                          2  quantize_fp8_sr:2 
v_pk_fma_f16                     155080  fattn-tile-instance-dkq512-dv512:36864 fattn-tile-instance-dkq128-dv128:29568 fattn-tile-instance-dkq576-dv512:22528 
v_pk_mul_f16                      21545  fattn-mma-f16-instance-ncols1_8-ncols2_8:1672 fattn-mma-f16-instance-ncols1_32-ncols2_2:1672 fattn-mma-f16-instance-ncols1_16-ncols2_4:1672 
