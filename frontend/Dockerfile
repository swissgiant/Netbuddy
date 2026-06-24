# NetBuddy Frontend — Vite-Build, ausgeliefert via nginx (statisch + API-Reverse-Proxy + TLS).
FROM node:22-bookworm-slim AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . ./
RUN npm run build


FROM nginx:1.27-alpine AS runtime
COPY nginx.conf /etc/nginx/templates/default.conf.template
# Zertifikate werden per Volume gemountet (docker/certs). Frontend-Build ins Web-Root.
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80 443
