FROM node:24-bookworm-slim
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts && npm cache clean --force
COPY auth.mjs server.mjs ./
RUN mkdir /data && chown node:node /data
ENV NODE_ENV=production PORT=4100 BOARD_DATA_DIR=/data
USER node
EXPOSE 4100
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD node -e 'fetch("http://127.0.0.1:" + process.env.PORT + "/healthz").then(r => process.exit(r.ok ? 0 : 1), () => process.exit(1))'
CMD ["node", "server.mjs"]
