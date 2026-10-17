# Decision Cortex web image: build the Vite SPA, serve it (and the API routes)
# from Caddy. Build context is the repo root (compose sets `context: ..`).
FROM node:22-alpine AS build

WORKDIR /app
# Copy manifests first so `npm ci` is cached until dependencies change.
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web ./
RUN npm run build

FROM caddy:2-alpine AS runtime

# The Caddyfile routes /ask, /node/*, /healthz to `api:8000` and serves the
# built SPA from /srv; see infra/Caddyfile for the handle-block ordering note.
COPY infra/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv
