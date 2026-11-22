# The front end (web/) on nginx, for Cloud Run. Built from a staging folder made by scripts/deploy_web.sh:
#   site/     the files of web/ the browser needs (no *.md, no mock server)
#   docker/   this file's neighbours (entrypoint script)
# What the image adds: the three libraries that index.html loads from unpkg.com are served from /vendor/ (no third-party CDN on the day), a proxy of /api/ to the VM (so the phone talks to one domain only) and,
# optionally, a cache of the OpenStreetMap tiles. See docs/WEB_DEPLOY.md.
FROM nginx:1.27-alpine

# site/ holds the files of web/ and site/vendor/ with the three libraries (downloaded and checked against a pinned SHA-256 by
# scripts/deploy_web.sh, so that building the image needs no network)
COPY site/ /usr/share/nginx/html/
RUN test -s /usr/share/nginx/html/vendor/maplibre-gl.css && test -s /usr/share/nginx/html/vendor/maplibre-gl.js \
 && test -s /usr/share/nginx/html/vendor/turf.min.js && sed -i '/sourceMappingURL/d' /usr/share/nginx/html/vendor/maplibre-gl.js

# index.html: the libraries come from /vendor/ (the same versions)
RUN sed -i \
      -e 's#https://unpkg.com/maplibre-gl@3.6.2/dist/maplibre-gl.css#vendor/maplibre-gl.css#' \
      -e 's#https://unpkg.com/maplibre-gl@3.6.2/dist/maplibre-gl.js#vendor/maplibre-gl.js#' \
      -e 's#https://unpkg.com/@turf/turf@7.1.0/turf.min.js#vendor/turf.min.js#' \
      /usr/share/nginx/html/index.html \
 && ! grep -q 'unpkg.com' /usr/share/nginx/html/index.html

COPY docker/40-web-config.sh /docker-entrypoint.d/40-web-config.sh
RUN chmod +x /docker-entrypoint.d/40-web-config.sh

# Settings (change them with `gcloud run services update --update-env-vars ...`, no rebuild):
#   API_UPSTREAM   where /api/ goes (the VM behind Caddy); the address changes when the VM gets a new external IP
#   FRONT_API_URL  the API address written in the front end code, replaced by /api/v1 while serving
#   TILE_CACHE     1: the OpenStreetMap tiles go through a cache of this service; 0: the browser asks OpenStreetMap directly
ENV PORT=8080 \
    API_UPSTREAM=https://34-118-11-71.nip.io \
    FRONT_API_URL=https://34-118-11-71.nip.io/api/v1 \
    TILE_CACHE=1
EXPOSE 8080
