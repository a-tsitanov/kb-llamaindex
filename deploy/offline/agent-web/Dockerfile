# DeepSeek Harness (dsh) Web UI for the offline cluster. Everything is baked at
# build time (npm + web profile init) so the container starts with no internet.
FROM node:22-slim
ARG DSH_VERSION=0.2.0-rc.2
ENV DSH_HOME=/data/dsh \
    DSH_TELEMETRY_DISABLED=1 \
    NODE_ENV=production
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates curl ripgrep python3 \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g @deepseek-ai/dsh@${DSH_VERSION} --no-audit --no-fund \
    && npm cache clean --force
# Initialize the shipped web profile now (first boot otherwise materializes it).
RUN mkdir -p /data/dsh /workspace && cd /workspace && dsh --profile web --dump-config >/dev/null
# KB upload plugin source; entrypoint installs it into the web profile's
# node_modules (the loader only resolves dsh's own deps + declared profile deps).
COPY plugin-kb-ingest/ /opt/dsh/plugins/dsh-kb-ingest/
COPY cordis.patch.yml /opt/dsh/cordis.patch.yml
COPY lan-proxy.mjs /opt/dsh/lan-proxy.mjs
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh
WORKDIR /workspace
EXPOSE 3080
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
