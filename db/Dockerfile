FROM mongo:8.0

LABEL org.opencontainers.image.title="field-under-pressure-mongodb" \
      org.opencontainers.image.description="MongoDB database for S.A.G.E. — Smart Agricultural Guidance Engine"

ENV MONGO_INITDB_DATABASE=field_under_pressure

# Bundle database archives and auto-restore the latest dump on first container initialization
COPY backups/ /backups/
COPY scripts/init-restore.sh /docker-entrypoint-initdb.d/01-restore-latest.sh

EXPOSE 27017
