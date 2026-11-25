# AXERP Production Dockerfile
# Base: frappe/erpnext:<ERPNEXT_VERSION> (arm64 + amd64 multi-arch)
# Bundled apps:
#   frappe/hrms        @ HRMS_VERSION    (HR, Payroll, Leave, Expenses)
#   frappe/crm         @ CRM_VERSION     (Sales CRM)
#   frappe/insights    @ INSIGHTS_VERSION (Analytics — develop branch for v16 support)
#
# Build:
#   docker build --platform linux/arm64 -f docker/Dockerfile \
#     -t axerp:v16.36.1-axerp -t axerp:prod .

ARG ERPNEXT_VERSION=v16.36.1
ARG HRMS_VERSION=version-16
ARG CRM_VERSION=main
# develop is v16-compatible. Its frontend imports @framework/ui modules that
# the v16.36.1 base image does not ship; those are copied in below.
ARG INSIGHTS_VERSION=develop
ARG WIKI_VERSION=version-3
ARG BLOG_VERSION=develop

FROM frappe/erpnext:${ERPNEXT_VERSION} AS builder

# Re-declare ARGs after FROM — Docker ARGs before FROM are out of scope
# inside a build stage unless explicitly re-declared (no default = inherits global)
ARG HRMS_VERSION
ARG CRM_VERSION
ARG INSIGHTS_VERSION
ARG WIKI_VERSION
ARG BLOG_VERSION

USER root

# ── HRMS ──────────────────────────────────────────────────────────────────
RUN git clone --depth 1 --branch ${HRMS_VERSION} \
      https://github.com/frappe/hrms.git \
      /home/frappe/frappe-bench/apps/hrms \
    && chown -R frappe:frappe /home/frappe/frappe-bench/apps/hrms

# ── CRM ───────────────────────────────────────────────────────────────────
RUN git clone --depth 1 --branch ${CRM_VERSION} \
      https://github.com/frappe/crm.git \
      /home/frappe/frappe-bench/apps/crm \
    && chown -R frappe:frappe /home/frappe/frappe-bench/apps/crm

# ── Insights ──────────────────────────────────────────────────────────────
RUN git clone --depth 1 --branch ${INSIGHTS_VERSION} \
      https://github.com/frappe/insights.git \
      /home/frappe/frappe-bench/apps/insights \
 && chown -R frappe:frappe /home/frappe/frappe-bench/apps/insights

# Insights develop imports @framework/ui/telemetry, TrialBanner, and the island
# builder. Those landed on frappe develop after the v16.36.1 image was built.
# Copy only the missing paths onto the base image's frappe ui package.
RUN git clone --depth 1 --filter=blob:none --sparse --branch develop \
      https://github.com/frappe/frappe.git /tmp/frappe-ui \
 && git -C /tmp/frappe-ui sparse-checkout set \
      ui/src/telemetry \
      ui/src/components/TrialBanner \
      ui/island \
      ui/vite/island \
      ui/patches \
 && UI=/home/frappe/frappe-bench/apps/frappe/ui \
 && cp -a /tmp/frappe-ui/ui/src/telemetry "${UI}/src/telemetry" \
 && cp -a /tmp/frappe-ui/ui/src/components/TrialBanner "${UI}/src/components/TrialBanner" \
 && cp -a /tmp/frappe-ui/ui/island "${UI}/island" \
 && cp -a /tmp/frappe-ui/ui/vite/island "${UI}/vite/island" \
 && if [ -d /tmp/frappe-ui/ui/patches ]; then cp -a /tmp/frappe-ui/ui/patches "${UI}/patches"; fi \
 && python3 -c 'import json; p="/home/frappe/frappe-bench/apps/frappe/ui/package.json"; pkg=json.load(open(p)); e=pkg.setdefault("exports", {}); e.setdefault("./island", {"import": "./island/index.js"}); e.setdefault("./island/host", {"import": "./island/host.js"}); e["./island/Island.vue"]="./island/Island.vue"; e.setdefault("./vite/island", {"import": "./vite/island/index.js"}); f=open(p,"w"); json.dump(pkg, f, indent=2); f.write("\n"); f.close()' \
 && rm -rf /tmp/frappe-ui \
 && chown -R frappe:frappe /home/frappe/frappe-bench/apps/frappe/ui

# ── Wiki ──────────────────────────────────────────────────────────────────
RUN git clone --depth 1 --branch ${WIKI_VERSION} \
      https://github.com/frappe/wiki.git \
      /home/frappe/frappe-bench/apps/wiki \
    && chown -R frappe:frappe /home/frappe/frappe-bench/apps/wiki

# ── Blog ──────────────────────────────────────────────────────────────────
RUN git clone --depth 1 --branch ${BLOG_VERSION} \
      https://github.com/frappe/blog.git \
      /home/frappe/frappe-bench/apps/blog \
    && chown -R frappe:frappe /home/frappe/frappe-bench/apps/blog

# ── AXERP (rebranded ERPNext) ──────────────────────────────────────────────
COPY --chown=frappe:frappe . /home/frappe/frappe-bench/apps/erpnext

USER frappe
WORKDIR /home/frappe/frappe-bench

# Install into the bench virtualenv explicitly.
# Plain `pip` resolves to ~/.local/bin/pip (user packages), which bench's
# virtualenv can't see. env/bin/pip installs into the venv's site-packages.
RUN env/bin/pip install --no-cache-dir -e apps/erpnext
RUN env/bin/pip install --no-cache-dir -e apps/hrms
RUN env/bin/pip install --no-cache-dir -e apps/crm
RUN env/bin/pip install --no-cache-dir -e apps/insights
RUN env/bin/pip install --no-cache-dir -e apps/wiki
RUN env/bin/pip install --no-cache-dir -e apps/blog

# hrms imports html2canvas in hierarchy_chart_desktop.js but it is not
# declared as a dependency in hrms/package.json — add it before bench build.
# yarn add triggers hrms postinstall (cd frontend && yarn install) which is fine.
RUN cd apps/hrms && yarn add html2canvas --silent

# frappe's esbuild.js detects missing node_modules and runs
# `yarn install --frozen-lockfile` in the app root (apps/crm/).
# If the CRM main branch lockfile is out of sync with package.json this fails.
# Pre-install in both the app root and frontend/ with --no-frozen-lockfile
# so the lockfile is current before frappe's frozen check runs.
RUN cd apps/crm && yarn install --no-frozen-lockfile --silent
RUN cd apps/crm/frontend && yarn install --no-frozen-lockfile --silent

# Insights frontend links @framework/ui to apps/frappe/ui. Install after the
# telemetry/TrialBanner/island overlay so the link and postinstall patches resolve.
RUN cd apps/insights/frontend && yarn install --no-frozen-lockfile --silent
# Desk Dashboard and Dashboard Chart render through these islands.
# bench build does not produce them; without this step assets.json 404s.
RUN cd apps/insights/frontend && yarn build:islands --production

# hrms Vite build imports socketio_port from sites/common_site_config.json
# at build time. This file doesn't exist during docker build (it's created
# at container startup by the configurator). Create a minimal stub so the
# import resolves without error.
RUN mkdir -p sites && \
    echo '{"socketio_port":9000,"db_host":"localhost","redis_cache":"redis://localhost:6379","redis_queue":"redis://localhost:6379"}' \
    > sites/common_site_config.json

# Build frontend assets for all apps.
# bench build compiles JS/CSS bundles via Node.
# CRM and insights use Vite and output to <app>/public/frontend/assets/ —
# these are baked here so the image ships complete assets at every tag.
RUN bench build --app erpnext
RUN bench build --app hrms
RUN bench build --app crm
RUN bench build --app insights
RUN bench build --app wiki
RUN bench build --app blog

# The frappe_docker entrypoint.sh does:
#   rm -rf sites/assets
#   ln -s /home/frappe/frappe-bench/assets sites/assets
# So the canonical asset path is BAKED_PATH=/home/frappe/frappe-bench/assets.
# We must populate THAT directory (not sites/assets/) with all app public dirs
# so the symlink resolves correctly in both backend and frontend containers.
RUN set -e; \
    BENCH=/home/frappe/frappe-bench; \
    BAKED=${BENCH}/assets; \
    mkdir -p "${BAKED}"; \
    for APP in frappe erpnext hrms crm insights wiki blog; do \
      SRC="${BENCH}/apps/${APP}/${APP}/public"; \
      DST="${BAKED}/${APP}"; \
      if [ -d "${SRC}" ]; then \
        rm -rf "${DST}"; \
        cp -r "${SRC}" "${DST}"; \
        COUNT=$(find "${DST}" -type f | wc -l); \
        echo "Baked ${APP}: ${COUNT} files into assets/"; \
      fi; \
    done; \
    # Also copy assets.json and assets-rtl.json from sites/assets/ \
    for F in assets.json assets-rtl.json; do \
      [ -f "${BENCH}/sites/assets/${F}" ] && cp "${BENCH}/sites/assets/${F}" "${BAKED}/${F}"; \
    done; \
    echo "Baked path contents:"; ls "${BAKED}/"

# Blog icon override — upstream ships teal #016E7D; AXERP uses orange
COPY --chown=frappe:frappe docker/blog-orange.svg /home/frappe/frappe-bench/assets/blog/blog.svg

FROM builder AS final
LABEL org.opencontainers.image.title="AXERP" \
      org.opencontainers.image.description="Operating System for Carbon Sovereignty" \
      org.opencontainers.image.vendor="Axina Group Inc." \
      org.opencontainers.image.source="https://github.com/axinagroup/axerp" \
      org.opencontainers.image.version="${ERPNEXT_VERSION}"
