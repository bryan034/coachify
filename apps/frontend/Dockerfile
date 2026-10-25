FROM node:24-bookworm-slim AS dependencies
WORKDIR /repo
COPY package.json package-lock.json ./
COPY apps/frontend/package.json apps/frontend/package.json
RUN npm ci

FROM dependencies AS development
ENV NODE_ENV=development NEXT_TELEMETRY_DISABLED=1
COPY --chown=node:node apps/frontend apps/frontend
RUN mkdir -p apps/frontend/.next && chown -R node:node apps/frontend/.next
USER node
EXPOSE 3000
CMD ["npm", "run", "dev", "--workspace", "apps/frontend", "--", "--hostname", "0.0.0.0", "--webpack"]

FROM dependencies AS build
COPY apps/frontend apps/frontend
ARG NEXT_PUBLIC_GOOGLE_CLIENT_ID
ENV NEXT_PUBLIC_GOOGLE_CLIENT_ID=$NEXT_PUBLIC_GOOGLE_CLIENT_ID NEXT_TELEMETRY_DISABLED=1
RUN npm run build --workspace apps/frontend && npm prune --omit=dev

FROM node:24-bookworm-slim AS production
WORKDIR /repo
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
COPY --from=build --chown=node:node /repo /repo
USER node
EXPOSE 3000
CMD ["npm", "run", "start", "--workspace", "apps/frontend", "--", "--hostname", "0.0.0.0"]
