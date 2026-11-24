# Flowmerce hosted image: Next.js frontend (public, behind the sign-in gate) + Python API (container-internal)
# + Litestream (keeps the SEO SQLite database in Supabase Storage). Start: scripts/run_hosted.py.
# See docs/operations/hosting-render.md. Build context: this Flowmerce/ folder.

# ---- 1. Frontend build ----
FROM node:24-trixie-slim AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# The /api forwarding target is fixed at build time: the API listens inside the container on 18787.
# FLOWMERCE_HOSTED=1 at build time keeps the local-only /login -> Home redirect out of this build.
ENV FLOWMERCE_API_ORIGIN=http://127.0.0.1:18787 NEXT_TELEMETRY_DISABLED=1 FLOWMERCE_HOSTED=1
RUN npm run build && npm prune --omit=dev

# ---- 2. Runtime ----
FROM python:3.14-slim-trixie
ARG LITESTREAM_VERSION=0.5.17
ARG LITESTREAM_SHA256=cfb371176d164437ae869f8351cfde49bd1804ae71c61923f75c9cba9c9c006d
# Memory (512 MB on Render's free plan): it ran out of memory twice and failed its health check twice on 2026-11-23
# with the CRO warm-up on and up to 4,000 Shopify answers kept. The hosted copy keeps fewer, reads pages on demand,
# and stops glibc giving each of its many threads its own memory arena (MALLOC_ARENA_MAX). The deep recommendations
# and landing page deep dive (2026-11-23) read more reports at once, so each report runs 3 Shopify queries at a time
# instead of 8 (CRO_READ_WORKERS).
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FLOWMERCE_ROOT=/app NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 FLOWMERCE_HOSTED=1 PORT=10000 \
    CRO_WARM_VIEWS=false CRO_CACHE_MAX=500 MALLOC_ARENA_MAX=2 CRO_READ_WORKERS=3

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
 && curl -fsSL -o /tmp/litestream.tgz \
      "https://github.com/benbjohnson/litestream/releases/download/v${LITESTREAM_VERSION}/litestream-${LITESTREAM_VERSION}-linux-x86_64.tar.gz" \
 && echo "${LITESTREAM_SHA256}  /tmp/litestream.tgz" | sha256sum -c - \
 && tar -xzf /tmp/litestream.tgz -C /usr/local/bin litestream \
 && rm /tmp/litestream.tgz && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

# Node runtime only (no npm needed at run time).
COPY --from=web /usr/local/bin/node /usr/local/bin/node

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --no-cache-dir ".[seo]"
COPY scripts/ scripts/
COPY deploy/ deploy/
COPY db/ db/
COPY --from=web /app/frontend/.next frontend/.next
COPY --from=web /app/frontend/node_modules frontend/node_modules
COPY --from=web /app/frontend/public frontend/public
COPY --from=web /app/frontend/package.json /app/frontend/next.config.mjs /app/frontend/redirects.mjs frontend/

RUN useradd --create-home --uid 10001 flowmerce && mkdir -p data secrets backups logs && chown -R flowmerce /app
USER flowmerce
EXPOSE 10000
CMD ["python", "scripts/run_hosted.py"]
