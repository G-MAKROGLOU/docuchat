# syntax=docker/dockerfile:1
FROM node:24.22.3-trixie-slim AS base
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /app
# Install and run as the image's uid 1000 user, so files written into a bind mount stay deletable.
RUN chown node:node /app
USER node

FROM base AS deps
COPY --chown=node:node package.json package-lock.json ./
RUN --mount=type=cache,target=/home/node/.npm,uid=1000 npm ci --no-audit --no-fund

# Development: source is bind mounted, node_modules and .next live in their own volumes.
FROM deps AS dev
COPY --chown=node:node . .
# The .next volume takes its owner from this folder; without it Docker creates it as root.
RUN mkdir -p .next
EXPOSE 3000
CMD ["npm", "run", "dev"]

FROM deps AS build
COPY --chown=node:node . .
RUN npm run build

FROM base AS prod
ENV NODE_ENV=production HOSTNAME=0.0.0.0 PORT=3000
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
EXPOSE 3000
CMD ["node", "server.js"]
