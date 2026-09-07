# syntax=docker/dockerfile:1.7
FROM node:22-bookworm-slim AS build
WORKDIR /app

# Copy only lockfile-adjacent files first so subsequent source changes
# don't invalidate the npm install layer.
COPY package.json package-lock.json ./

# Install with the lockfile. The BuildKit cache mount persists npm's
# content-addressable package cache between builds, turning cold
# installs (~60-90s) into near-instant rehydration. --include=optional
# is set explicitly so the platform-specific Rollup binary (e.g.
# @rollup/rollup-linux-x64-gnu or @rollup/rollup-linux-arm64-gnu) is
# pulled from optionalDependencies — this is what the previous
# `rm -f package-lock.json && npm install` workaround was papering over.
RUN --mount=type=cache,target=/root/.npm \
    npm ci --include=optional

COPY . .

# Browser-visible deployment configuration is supplied explicitly at build time.
ARG VITE_API_URL
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_ANON_KEY
ENV VITE_API_URL=${VITE_API_URL} \
    VITE_SUPABASE_URL=${VITE_SUPABASE_URL} \
    VITE_SUPABASE_ANON_KEY=${VITE_SUPABASE_ANON_KEY}

# Build mode can be overridden with a build argument.
ARG BUILD_MODE=production
RUN npm run build -- --mode ${BUILD_MODE}

FROM nginx:stable-alpine AS production
ENV PORT=80
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/templates/default.conf.template
EXPOSE ${PORT}
CMD /bin/sh -c "envsubst '\$PORT' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf && nginx -g 'daemon off;'"
