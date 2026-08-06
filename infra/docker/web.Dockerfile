FROM node:20-alpine AS base

WORKDIR /app

RUN corepack enable && corepack prepare pnpm@9 --activate

COPY pnpm-workspace.yaml package.json /app/
COPY apps/web/package.json /app/apps/web/package.json
COPY packages/botclaw-spec/package.json /app/packages/botclaw-spec/package.json

# dev 镜像不做 tree-shake, 全量装依赖便于 hot reload
RUN pnpm install --no-frozen-lockfile

COPY apps/web /app/apps/web
COPY packages/botclaw-spec /app/packages/botclaw-spec

WORKDIR /app/apps/web
EXPOSE 5173
CMD ["pnpm", "dev", "--host", "0.0.0.0"]
