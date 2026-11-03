# Builds web/ to static files and copies them into the `site` volume (served by Caddy).
FROM node:22-alpine AS build
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM alpine:3.21
COPY --from=build /web/dist /dist
CMD ["/bin/sh", "-c", "rm -rf /site/* && cp -r /dist/. /site/ && echo 'site copied'"]
