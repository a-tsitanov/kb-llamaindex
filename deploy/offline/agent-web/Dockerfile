# Agent web UI for the offline cluster: DeepSeek Harness (dsh, MIT) rebranded
# at build time (BRAND_NAME / BRAND_SHORT). Everything is baked at build time
# (npm + web profile init) so the container starts with no internet.
#   docker buildx build --platform linux/amd64 -t agent-web:offline \
#     [--build-arg BRAND_NAME="KB Ассистент" --build-arg BRAND_SHORT=KB] deploy/offline/agent-web
FROM node:22-slim
ARG DSH_VERSION=0.2.0-rc.2
ARG BRAND_NAME="KB Ассистент"
ARG BRAND_SHORT="KB"
ENV DSH_HOME=/data/dsh \
    DSH_TELEMETRY_DISABLED=1 \
    NODE_ENV=production
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates curl ripgrep python3 \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g @deepseek-ai/dsh@${DSH_VERSION} --no-audit --no-fund \
    && npm cache clean --force
# Initialize the shipped web profile now (first boot otherwise materializes it).
RUN mkdir -p /data/dsh /workspace && cd /workspace && dsh --profile web --dump-config >/dev/null
# Local plugins (entrypoint installs /opt/dsh/plugins/* into the web profile's
# node_modules: the loader only resolves dsh's own deps + declared profile deps).
COPY plugin-kb-ingest/ /opt/dsh/plugins/dsh-kb-ingest/
COPY plugin-brand/ /opt/dsh/plugins/kb-brand/
COPY plugin-locale-ru/ /opt/dsh/plugins/kb-locale-ru/
COPY brand/ /opt/dsh/brand/
# Rebrand: title/manifest/favicons, Russian language pack (kb-locale-ru), UI strings, system prompt identity, startup
# log prefix, kb-brand placeholders. GUARD: fail the build if a user-visible
# "DeepSeek Harness" survives in the served bundles / prompt / web host strings
# (bundle names are hashed, hence find+grep over whole dirs).
RUN BRAND_NAME="${BRAND_NAME}" BRAND_SHORT="${BRAND_SHORT}" node /opt/dsh/brand/rebrand.mjs \
    && NM=/usr/local/lib/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai \
    && for f in $(find $NM/dsh-client-ui-*/lib $NM/dsh-system-prompt/lib $NM/dsh-web-app/lib /opt/dsh/plugins/kb-brand/lib /opt/dsh/plugins/kb-locale-ru/lib -name '*.js'); do node --check "$f" || exit 1; done \
    && if grep -rIl --include='*.js' --include='*.html' --include='*.webmanifest' "DeepSeek Harness" \
         $NM/dsh-web-frontend/dist $NM/dsh-client-ui-*/lib $NM/dsh-system-prompt/lib $NM/dsh-web-app/lib; then \
         echo "rebrand guard: 'DeepSeek Harness' still present in the files above" >&2; exit 1; fi \
    && if grep -rlE "__BRAND_|__RU_DICT__" /opt/dsh/plugins/kb-brand /opt/dsh/plugins/kb-locale-ru/lib $NM/dsh-web-frontend/dist; then \
         echo "rebrand guard: unsubstituted placeholder" >&2; exit 1; fi
COPY cordis.patch.yml /opt/dsh/cordis.patch.yml
COPY lan-proxy.mjs /opt/dsh/lan-proxy.mjs
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh
LABEL org.opencontainers.image.title="agent-web" \
      org.opencontainers.image.description="KB agent web UI (DeepSeek Harness ${DSH_VERSION}, MIT, rebranded)"
WORKDIR /workspace
EXPOSE 3080
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
