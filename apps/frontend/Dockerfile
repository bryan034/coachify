FROM node:24-bookworm-slim AS build
WORKDIR /repo
COPY package.json package-lock.json ./
COPY apps/frontend/package.json apps/frontend/package.json
RUN npm ci
COPY apps/frontend apps/frontend
ARG NEXT_PUBLIC_GOOGLE_CLIENT_ID
ENV NEXT_PUBLIC_GOOGLE_CLIENT_ID=$NEXT_PUBLIC_GOOGLE_CLIENT_ID NEXT_TELEMETRY_DISABLED=1
RUN npm run build --workspace apps/frontend && npm prune --omit=dev

FROM node:24-bookworm-slim
WORKDIR /repo
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
COPY --from=build --chown=node:node /repo /repo
USER node
EXPOSE 3000
CMD ["npm", "run", "start", "--workspace", "apps/frontend", "--", "--hostname", "0.0.0.0"]
