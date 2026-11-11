#!/bin/sh

set -eu

: "${BIPME_API_UPSTREAM:?BIPME_API_UPSTREAM is required}"

case "$BIPME_API_UPSTREAM" in
    http://*) authority=${BIPME_API_UPSTREAM#http://} ;;
    https://*) authority=${BIPME_API_UPSTREAM#https://} ;;
    *) echo "BIPME_API_UPSTREAM must be an HTTP(S) origin" >&2; exit 1 ;;
esac

if ! printf '%s' "$authority" | grep -Eq '^([A-Za-z0-9.-]+|\[[0-9A-Fa-f:]+\])(:[0-9]{1,5})?$'; then
    echo "BIPME_API_UPSTREAM must contain only a host and optional port" >&2
    exit 1
fi

envsubst '${BIPME_API_UPSTREAM}' \
    < /etc/nginx/templates/default.conf.template \
    > /etc/nginx/conf.d/default.conf
envsubst '${BIPME_API_UPSTREAM}' \
    < /etc/nginx/templates/bipme-api-proxy.conf.template \
    > /etc/nginx/snippets/bipme-api-proxy.conf

exec "$@"
