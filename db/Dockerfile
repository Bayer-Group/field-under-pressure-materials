FROM mongo:8.0

LABEL org.opencontainers.image.title="field-under-pressure-mongodb" \
      org.opencontainers.image.description="MongoDB database for Hackathon GEO - Field Under Pressure (Crop Science)"

ENV MONGO_INITDB_DATABASE=field_under_pressure

# Automatically executed by the official mongo entrypoint on first database initialization
COPY scripts/seed.js /docker-entrypoint-initdb.d/01-seed-collections.js

EXPOSE 27017
