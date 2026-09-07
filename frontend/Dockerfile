# syntax=docker/dockerfile:1.7
FROM node:20-bookworm-slim AS build
WORKDIR /app

# Copy only lockfile-adjacent files first so subsequent source changes
# don't invalidate the (expensive) npm install layer. .npmrc carries
# legacy-peer-deps=true, which npm ci needs to accept eve's optional
# vite@^8 peer against this app's vite@5.
COPY package.json package-lock.json .npmrc ./

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

# Build mode can be overridden with build arg
ARG BUILD_MODE=production
RUN npm run build -- --mode ${BUILD_MODE}

FROM nginx:stable-alpine AS production
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/templates/default.conf.template
EXPOSE ${PORT}
CMD /bin/sh -c "envsubst '\$PORT' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf && nginx -g 'daemon off;'"