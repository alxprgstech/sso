# syntax=docker/dockerfile:1
FROM node:24-alpine AS builder
ARG ALX_BUILD_SHA
ENV ALX_BUILD_SHA=$ALX_BUILD_SHA

WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY VERSION /app/VERSION
COPY frontend /app/frontend
RUN npm run build && test -z "$(find dist -name '*.map' -print -quit)"

FROM nginx:1.27-alpine

COPY --from=builder /app/frontend/dist /usr/share/nginx/html
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY frontend/csp.conf /etc/nginx/snippets/sso-csp.conf
COPY frontend/security-headers.conf /etc/nginx/snippets/sso-security-headers.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
