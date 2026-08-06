ARG ROCM_RUNTIME_BASE_IMAGE
FROM ${ROCM_RUNTIME_BASE_IMAGE}

ARG PYPI_INDEX_URL
ARG LLAMA_CPP_REPOSITORY
ARG LLAMA_CPP_REVISION

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PIP_INDEX_URL=${PYPI_INDEX_URL}

WORKDIR /opt/agentfactory

COPY pyproject.toml uv.lock README.md /opt/agentfactory/
COPY agent_factory /opt/agentfactory/agent_factory

RUN python -m pip install --no-cache-dir -e /opt/agentfactory \
    && python -m pip install --no-cache-dir "sentence-transformers>=3,<6" "transformers>=4.51,<6" \
    && python -c "import torch; assert torch.version.hip, 'ROCm PyTorch build is required'" \
    && python -c "import sentence_transformers"

RUN test -n "${LLAMA_CPP_REPOSITORY}" \
    && test -n "${LLAMA_CPP_REVISION}" \
    && git clone "${LLAMA_CPP_REPOSITORY}" /opt/llama.cpp \
    && git -C /opt/llama.cpp checkout "${LLAMA_CPP_REVISION}" \
    && cmake -S /opt/llama.cpp -B /opt/llama.cpp/build -G Ninja -DGGML_HIP=ON -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr/local \
    && cmake --build /opt/llama.cpp/build --target llama-server -j 8 \
    && cmake --install /opt/llama.cpp/build \
    && ldconfig

ENV AGENTFACTORY_LLAMA_SERVER_PATH=/usr/local/bin/llama-server

CMD ["python", "-m", "agent_factory.local_inference.run_llama_server", "--help"]
