# syntax=docker/dockerfile:1.7
FROM node:22.17.1-alpine3.22@sha256:5539840ce9d013fa13e3b9814c9353024be7ac75aca5db6d039504a56c04ea59 AS web
WORKDIR /source/web
COPY web/package.json web/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build \
    && mkdir -p /out/font-licenses/ibm-plex-mono /out/font-licenses/newsreader \
    && cp node_modules/@fontsource/ibm-plex-mono/LICENSE \
      /out/font-licenses/ibm-plex-mono/OFL-1.1.txt \
    && cp node_modules/@fontsource/newsreader/LICENSE \
      /out/font-licenses/newsreader/OFL-1.1.txt

FROM golang:1.25.12-alpine3.23@sha256:cc985ef6f9c3bf9ece7488129c9abe0a150388ccdfa428d886fc709dca0b230a AS backend
WORKDIR /source
RUN apk add --no-cache git
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY . .
ARG SOURCE_COMMIT=unknown
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build \
      -trimpath -ldflags="-s -w -X main.buildCommit=${SOURCE_COMMIT}" \
      -o /out/signalforge-workspace ./cmd/signalforge-workspace
RUN sh scripts/build_runtime_license_bundle.sh /out/licenses

FROM alpine:3.23@sha256:fd791d74b68913cbb027c6546007b3f0d3bc45125f797758156952bc2d6daf40
ARG SOURCE_COMMIT=unknown
ARG BUILD_VERSION=development
ARG BUILD_DATE=unknown
LABEL org.opencontainers.image.title="SignalForge" \
      org.opencontainers.image.description="Private, evidence-grounded investor intelligence on AMD Radeon" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.source="https://github.com/rvbernucci/signalforge" \
      org.opencontainers.image.revision="${SOURCE_COMMIT}" \
      org.opencontainers.image.version="${BUILD_VERSION}" \
      org.opencontainers.image.created="${BUILD_DATE}"
RUN apk add --no-cache ca-certificates tzdata \
    && addgroup -S -g 10001 signalforge \
    && adduser -S -D -H -u 10001 -G signalforge signalforge \
    && mkdir -p /app/web /app/fixtures /var/lib/signalforge/audit /var/lib/signalforge/logs /var/lib/signalforge/traces \
    && chown -R signalforge:signalforge /var/lib/signalforge
WORKDIR /app
COPY --from=backend /out/signalforge-workspace /usr/local/bin/signalforge-workspace
COPY --from=web /source/web/dist ./web/dist
COPY --from=backend /out/licenses ./licenses
COPY --from=web /out/font-licenses ./licenses/fonts
COPY fixtures/workspace ./fixtures/workspace
COPY fixtures/golden ./fixtures/golden
COPY fixtures/retrieval ./fixtures/retrieval
COPY fixtures/productscope ./fixtures/productscope
RUN cd /app/licenses \
    && find . -type f ! -name SHA256SUMS -print \
      | LC_ALL=C sort \
      | xargs sha256sum > SHA256SUMS \
    && test -s project/LICENSE \
    && test -s project/NOTICE \
    && test -s project/THIRD_PARTY_NOTICES.md \
    && test -s fonts/ibm-plex-mono/OFL-1.1.txt \
    && test -s fonts/newsreader/OFL-1.1.txt \
    && test -s GO_MODULES.tsv
USER 10001:10001
EXPOSE 8080
VOLUME ["/var/lib/signalforge"]
ENTRYPOINT ["/usr/local/bin/signalforge-workspace"]
CMD ["--listen", "0.0.0.0:8080", "--allow-container-listen", "--mode", "fixture", "--static-dir", "/app/web/dist", "--fixture", "/app/fixtures/workspace/golden-case.json", "--snapshot", "/app/fixtures/golden/financial-snapshot.json", "--retrieval", "/app/fixtures/retrieval/golden-eval.json", "--price-inputs", "/app/fixtures/golden/market-price-inputs.json", "--case-db", "/var/lib/signalforge/cases.db", "--audit-dir", "/var/lib/signalforge/audit", "--trace-dir", "/var/lib/signalforge/traces", "--event-log", "/var/lib/signalforge/logs/events.jsonl"]
