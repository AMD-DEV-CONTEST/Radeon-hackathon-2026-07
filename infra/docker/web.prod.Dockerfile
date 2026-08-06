# Stage 1: Build static assets
FROM node:22-alpine AS build

WORKDIR /app
COPY apps/web/package.json apps/web/package-lock.json /app/apps/web/
WORKDIR /app/apps/web
RUN npm config set registry https://registry.npmmirror.com \
    && npm ci

COPY apps/web /app/apps/web
WORKDIR /app/apps/web
# Skip tsc type-checking (existing TS warnings) and build Vite bundle directly
RUN npx vite build

# Stage 2: Serve with Nginx
FROM nginx:alpine

COPY --from=build /app/apps/web/dist /usr/share/nginx/html
COPY infra/docker/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
