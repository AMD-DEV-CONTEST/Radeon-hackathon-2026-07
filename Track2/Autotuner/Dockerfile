FROM rocm/vllm:rocm7.14.0_rdna_ubuntu24.04_py3.14_pytorch_2.11.0_vllm_0.23.0

WORKDIR /workspace/autotuner
COPY . /workspace/autotuner
RUN python -m pip install --no-deps .

ENTRYPOINT ["autotuner"]
CMD ["inspect"]
