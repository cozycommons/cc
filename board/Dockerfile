FROM node:22-bookworm-slim AS web
WORKDIR /build/frontend
COPY --chmod=644 frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY frontend/chat.html frontend/vite.chat.config.js ./
COPY frontend/src/chat ./src/chat
COPY frontend/src/design/system ./src/design/system
COPY design/cozy-wabi /build/design/cozy-wabi
RUN npm run build:chat

FROM node:24-bookworm-slim
WORKDIR /app
COPY --chmod=644 board/package.json board/package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts && npm cache clean --force
COPY --chmod=644 board/auth.mjs board/server.mjs ./
COPY --from=web /build/frontend/dist-chat /app/web
RUN mkdir /data && chown node:node /data
ENV NODE_ENV=production PORT=4100 BOARD_DATA_DIR=/data BOARD_WEB_DIR=/app/web
USER node
EXPOSE 4100
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD node -e 'fetch("http://127.0.0.1:" + process.env.PORT + "/healthz").then(r => process.exit(r.ok ? 0 : 1), () => process.exit(1))'
CMD ["node", "server.mjs"]
