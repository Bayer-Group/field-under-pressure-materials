#!/bin/sh
# Writes the nginx configuration of the front end from the environment (runs at every start of the container).
# See docker/web/Dockerfile for the settings and docs/WEB_DEPLOY.md for what each part does.
set -eu

PORT="${PORT:-8080}"
API_UPSTREAM="${API_UPSTREAM%/}"
FRONT_API_URL="${FRONT_API_URL:-}"
TILE_CACHE="${TILE_CACHE:-1}"
[ -n "$API_UPSTREAM" ] || { echo "API_UPSTREAM is empty" >&2; exit 1; }
API_HOST="${API_UPSTREAM#*://}"; API_HOST="${API_HOST%%/*}"

# nginx resolves the names of the proxy targets at run time, with the resolver of the platform (Cloud Run: from /etc/resolv.conf)
RESOLVER="$(awk '/^nameserver/ {print $2; exit}' /etc/resolv.conf 2>/dev/null || true)"
[ -n "$RESOLVER" ] || RESOLVER="8.8.8.8"
case "$RESOLVER" in *:*) RESOLVER="[$RESOLVER]" ;; esac

CONF=/etc/nginx/conf.d/default.conf
CACHE_CONF=/etc/nginx/conf.d/00-cache.conf
: > "$CACHE_CONF"

# index.html: the OpenStreetMap tiles through our cache; the JS files: the API address of the code becomes the same origin
SUB_HTML=""
SUB_JS=""
if [ "$TILE_CACHE" = "1" ]; then
  SUB_HTML="sub_filter \"'https://tile.openstreetmap.org/{z}/{x}/{y}.png'\" \"location.origin + '/osm/{z}/{x}/{y}.png'\";"
  cat > "$CACHE_CONF" <<EOF
proxy_cache_path /tmp/osm_cache levels=1:2 keys_zone=osm:20m max_size=300m inactive=7d use_temp_path=off;
EOF
fi
if [ -n "$FRONT_API_URL" ]; then
  SUB_JS="sub_filter \"$FRONT_API_URL\" \"/api/v1\";"
fi

TILE_LOCATION=""
if [ "$TILE_CACHE" = "1" ]; then
  # Only tile paths (z/x/y.png) are accepted, so this cannot be used as an open proxy. The policy of OpenStreetMap asks for an identifying
  # User-Agent; a cache keeps the load on their servers small when many people look at the same area.
  TILE_LOCATION="
    location ~ \"^/osm/[0-9]{1,2}/[0-9]{1,7}/[0-9]{1,7}\\\\.png\$\" {
        set \$tiles https://tile.openstreetmap.org;
        rewrite ^/osm/(.*)\$ /\$1 break;
        proxy_pass \$tiles\$uri;
        proxy_ssl_server_name on;
        proxy_set_header Host tile.openstreetmap.org;
        proxy_set_header User-Agent \"field-under-pressure-demo/1.0 (+https://github.com/geoearth-junction/field-under-pressure-materials)\";
        proxy_set_header Referer \"\";
        proxy_set_header Authorization \"\";
        proxy_set_header Cookie \"\";
        proxy_cache osm;
        proxy_cache_valid 200 7d;
        proxy_cache_valid 404 1m;
        proxy_cache_lock on;
        proxy_cache_use_stale error timeout updating http_500 http_502 http_503 http_504;
        proxy_connect_timeout 5s;
        proxy_read_timeout 15s;
        add_header Cache-Control \"public, max-age=86400\" always;
        add_header X-Cache \$upstream_cache_status always;
    }
"
fi

cat > "$CONF" <<EOF
resolver $RESOLVER valid=30s ipv6=off;

server {
    listen $PORT default_server;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;
    client_max_body_size 5m;

    gzip on;
    gzip_comp_level 5;
    gzip_proxied any;
    gzip_types text/css application/javascript text/javascript application/json text/plain image/svg+xml;

    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # the files have no version in their names: the browser asks again every time (a short answer, 304, when nothing changed)
    location = /index.html {
        add_header Cache-Control "no-cache" always;
        add_header X-Content-Type-Options "nosniff" always;
        sub_filter_once off;
        sub_filter_types text/html;
        $SUB_HTML
    }
    location = / {
        add_header Cache-Control "no-cache" always;
        add_header X-Content-Type-Options "nosniff" always;
        sub_filter_once off;
        sub_filter_types text/html;
        $SUB_HTML
        try_files /index.html =404;
    }
    location ~ \\.js\$ {
        add_header Cache-Control "no-cache" always;
        add_header X-Content-Type-Options "nosniff" always;
        sub_filter_once off;
        sub_filter_types application/javascript text/javascript;
        $SUB_JS
    }
    location ^~ /vendor/ {                  # ^~: wins over the regular expression of the .js files
        add_header Cache-Control "public, max-age=31536000, immutable" always;
        add_header X-Content-Type-Options "nosniff" always;
    }

    location = /healthz {
        access_log off;
        default_type text/plain;
        return 200 "ok\n";
    }

    # the API on the VM: the phone talks to this domain only (nothing else to be blocked by the network of the room, no CORS)
    location /api/ {
        set \$api $API_UPSTREAM;
        proxy_pass \$api\$request_uri;
        proxy_http_version 1.1;
        proxy_ssl_server_name on;
        proxy_ssl_name $API_HOST;
        proxy_set_header Host $API_HOST;
        proxy_set_header X-Forwarded-For \$http_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_connect_timeout 5s;
        proxy_read_timeout 60s;
        proxy_send_timeout 60s;
        add_header Cache-Control "no-store" always;
    }
$TILE_LOCATION
    location / {
        try_files \$uri =404;
    }
}
EOF

nginx -t
echo "web config: port $PORT, API -> $API_UPSTREAM (host $API_HOST), resolver $RESOLVER, tile cache $TILE_CACHE, API address in the code '${FRONT_API_URL:-none}'"
