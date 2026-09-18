FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /opt/buildguard

COPY pyproject.toml README.md ./
COPY src ./src
COPY configs ./configs
COPY docs ./docs

RUN python -m pip install --no-cache-dir .

RUN addgroup --system buildguard \
    && adduser --system --ingroup buildguard buildguard \
    && mkdir -p /opt/buildguard/workspace \
    && chown -R buildguard:buildguard /opt/buildguard

USER buildguard

EXPOSE 8000 8501

CMD ["buildguard", "serve-api", "--config", "configs/app.yaml"]
