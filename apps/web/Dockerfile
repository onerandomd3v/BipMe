FROM node:24-alpine AS build

WORKDIR /workspace/apps/web

RUN npm install --global pnpm@10.20.0

COPY apps/web/package.json apps/web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY apps/web/ ./
RUN pnpm build

FROM nginx/nginx-unprivileged:stable-alpine AS runtime

COPY --from=build --chown=nginx:nginx /workspace/apps/web/dist/ /usr/share/nginx/html/
COPY apps/web/nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY apps/web/nginx/snippets/bipme-api-proxy.conf /etc/nginx/templates/bipme-api-proxy.conf.template
COPY apps/web/nginx/snippets/ /etc/nginx/snippets/
COPY --chmod=755 apps/web/docker-entrypoint.sh /usr/local/bin/bipme-web-entrypoint

USER nginx
EXPOSE 8080
STOPSIGNAL SIGQUIT

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1

ENTRYPOINT ["/usr/local/bin/bipme-web-entrypoint"]
CMD ["nginx", "-g", "daemon off;"]
