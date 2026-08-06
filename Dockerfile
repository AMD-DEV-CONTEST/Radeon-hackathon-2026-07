# ROCm devices are supplied by the host; this image packages Python dependencies.
FROM mambaorg/micromamba:2.0.5

USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    libegl1 libgl1 libglib2.0-0 libxrender1 && \
    rm -rf /var/lib/apt/lists/*

USER $MAMBA_USER
WORKDIR /workspace
COPY --chown=$MAMBA_USER:$MAMBA_USER environment.yml /tmp/environment.yml
RUN micromamba create -y -f /tmp/environment.yml && micromamba clean --all --yes
COPY --chown=$MAMBA_USER:$MAMBA_USER . /workspace
ENV PATH=/opt/conda/envs/Radeon-hackathon-2026-07/bin:$PATH
CMD ["bash"]
