# syntax=docker/dockerfile:1
FROM node:24-alpine@sha256:ebfe2f90462722a7a4de65e91990e97fe0d401c70e0e762c5b53302f905ec1c1 AS builder
ARG ALX_BUILD_SHA
ENV ALX_BUILD_SHA=$ALX_BUILD_SHA

WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY VERSION /app/VERSION
COPY frontend /app/frontend
RUN npm run build && test -z "$(find dist -name '*.map' -print -quit)"

FROM nginx:1.30.5-alpine@sha256:0985e772fb9f729e6fa0980da05fca5d9c468e870eed43071545afa9d2e27d94
RUN apk add --no-cache --upgrade libexpat=2.8.5-r0 pcre2=10.49-r0

COPY --from=builder /app/frontend/dist /usr/share/nginx/html
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY frontend/csp.conf /etc/nginx/snippets/sso-csp.conf
COPY frontend/security-headers.conf /etc/nginx/snippets/sso-security-headers.conf
COPY frontend/nginx-main.conf /etc/nginx/nginx.conf
USER 101:101
ENTRYPOINT ["nginx"]

EXPOSE 8080

CMD ["-g", "daemon off;"]
