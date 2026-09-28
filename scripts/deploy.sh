#!/bin/bash
# Copyright (c) 2026 Axina Group Inc. Created by Daniel Brody. All rights reserved.
#
# AXERP Deploy Script — build on EC2, push to ECR, deploy via compose.
#
# Flow:
#   1. Package production branch → upload to S3 (source tarball)
#   2. Upload compose file → S3
#   3. Stage build + launch scripts on EC2 via SSM
#   4. EC2 builds image, pushes to ECR (010438486646.dkr.ecr.us-east-1.amazonaws.com/axerp)
#   5. EC2 docker compose up -d (pulls from ECR)
#   6. migrate service runs bench migrate + bench build --production
#   7. fix-assets-json.sh syncs assets backend→frontend, verifies 200s
#   8. Health checks from local machine
#
# Usage:
#   bash scripts/deploy.sh              # full deploy
#   bash scripts/deploy.sh --dry-run    # preview without executing
#   bash scripts/deploy.sh --skip-build # skip build, just redeploy + asset fix
#
# Prerequisites: aws CLI configured with ECR access, gh CLI authenticated.

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
EC2_INSTANCE="i-08de3cab7640d0c62"
AWS_REGION="us-east-1"
AWS_ACCOUNT="010438486646"
ECR_REGISTRY="${AWS_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com"
ECR_REPO="${ECR_REGISTRY}/axerp"
S3_BUCKET="axina-openproject-files"
S3_PREFIX="deploy"
SITE="erp.tspgusa.com"
COMPOSE_LOCAL="infrastructure/docker/docker-compose.axerp.yml"

DRY_RUN=false
SKIP_BUILD=false
for arg in "$@"; do
  [[ "$arg" == "--dry-run" ]]    && DRY_RUN=true
  [[ "$arg" == "--skip-build" ]] && SKIP_BUILD=true
done

# ── Helpers ───────────────────────────────────────────────────────────────────
log()  { echo "$(date -u +%H:%M:%S) ▶ $*"; }
ok()   { echo "$(date -u +%H:%M:%S) ✅ $*"; }
warn() { echo "$(date -u +%H:%M:%S) ⚠️  $*"; }
fail() { echo "$(date -u +%H:%M:%S) ❌ $*" >&2; exit 1; }

run() { $DRY_RUN && echo "  [dry-run] $*" || "$@"; }

ssm_run() {
  local description="$1"; shift
  local commands=("$@")
  log "${description}..."
  if $DRY_RUN; then echo "  [dry-run] SSM: ${commands[*]}"; return 0; fi

  local cmd_json
  cmd_json=$(printf '%s\n' "${commands[@]}" | python3 -c "
import json, sys
lines = sys.stdin.read().strip().splitlines()
print(json.dumps(lines))
")

  local cmd_id
  cmd_id=$(aws ssm send-command \
    --instance-ids "${EC2_INSTANCE}" \
    --document-name "AWS-RunShellScript" \
    --parameters "{\"commands\":${cmd_json}}" \
    --region "${AWS_REGION}" \
    --query "Command.CommandId" --output text)
  log "  SSM: ${cmd_id}"

  local status="InProgress" elapsed=0
  while [[ "$status" == "InProgress" || "$status" == "Pending" ]]; do
    sleep 10; elapsed=$((elapsed + 10))
    status=$(aws ssm get-command-invocation \
      --command-id "${cmd_id}" --instance-id "${EC2_INSTANCE}" \
      --region "${AWS_REGION}" --query "Status" --output text 2>/dev/null || echo "Pending")
    echo "  ${elapsed}s — ${status}"
    [[ $elapsed -ge 600 ]] && fail "SSM timed out after 10 min"
  done

  local out
  out=$(aws ssm get-command-invocation \
    --command-id "${cmd_id}" --instance-id "${EC2_INSTANCE}" \
    --region "${AWS_REGION}" --query "[StandardOutputContent,StandardErrorContent]" --output text)
  echo "── SSM output ──────────────────────────────────"
  echo "$out"
  echo "────────────────────────────────────────────────"
  if [[ "$status" != "Success" ]]; then fail "SSM failed: ${status}"; fi
}

poll_background_build() {
  log "Polling EC2 build (allow ~25 min)..."
  local elapsed=0
  while [[ $elapsed -lt 1800 ]]; do
    sleep 30; elapsed=$((elapsed + 30))

    local poll_id
    poll_id=$(aws ssm send-command \
      --instance-ids "${EC2_INSTANCE}" \
      --document-name "AWS-RunShellScript" \
      --parameters '{"commands":["cat /tmp/axerp-deploy-status 2>/dev/null || echo RUNNING"]}' \
      --region "${AWS_REGION}" \
      --query "Command.CommandId" --output text 2>/dev/null || echo "")
    [[ -z "$poll_id" ]] && { log "  ${elapsed}s — polling..."; continue; }

    # Wait for the SSM command to finish (not just 8s fixed sleep)
    local poll_status="InProgress" poll_waited=0
    while [[ "$poll_status" == "InProgress" || "$poll_status" == "Pending" ]]; do
      sleep 3; poll_waited=$((poll_waited + 3))
      poll_status=$(aws ssm get-command-invocation \
        --command-id "${poll_id}" --instance-id "${EC2_INSTANCE}" \
        --region "${AWS_REGION}" --query "Status" --output text 2>/dev/null || echo "Pending")
      [[ $poll_waited -ge 30 ]] && break  # cap at 30s — shouldn't take this long for a cat
    done
    local val
    val=$(aws ssm get-command-invocation \
      --command-id "${poll_id}" --instance-id "${EC2_INSTANCE}" \
      --region "${AWS_REGION}" --query "StandardOutputContent" --output text 2>/dev/null | tr -d '[:space:]')

    if [[ "$val" == "0" ]]; then
      ok "Build completed (${elapsed}s)"
      return 0
    elif [[ "$val" =~ ^[1-9][0-9]*$ ]]; then
      # Build failed — fetch log
      local log_id
      log_id=$(aws ssm send-command \
        --instance-ids "${EC2_INSTANCE}" --document-name "AWS-RunShellScript" \
        --parameters '{"commands":["tail -50 /tmp/axerp-deploy-run.log; echo ---; tail -30 /tmp/docker-build.log 2>/dev/null"]}' \
        --region "${AWS_REGION}" --query "Command.CommandId" --output text 2>/dev/null || echo "")
      if [[ -n "$log_id" ]]; then
        local _ls="InProgress" _lw=0
        while [[ "$_ls" == "InProgress" || "$_ls" == "Pending" ]]; do
          sleep 3; _lw=$((_lw+3))
          _ls=$(aws ssm get-command-invocation --command-id "${log_id}" --instance-id "${EC2_INSTANCE}" \
            --region "${AWS_REGION}" --query "Status" --output text 2>/dev/null || echo "Pending")
          [[ $_lw -ge 30 ]] && break
        done
      fi
      echo "── Build log (tail) ────────────────────────────"
      [[ -n "$log_id" ]] && aws ssm get-command-invocation \
        --command-id "${log_id}" --instance-id "${EC2_INSTANCE}" \
        --region "${AWS_REGION}" --query "StandardOutputContent" --output text 2>/dev/null
      echo "────────────────────────────────────────────────"
      fail "EC2 build failed (exit ${val}) after ${elapsed}s"
    else
      # Still running — show tail
      local tail_id
      tail_id=$(aws ssm send-command \
        --instance-ids "${EC2_INSTANCE}" --document-name "AWS-RunShellScript" \
        --parameters '{"commands":["tail -3 /tmp/axerp-deploy-run.log 2>/dev/null | tr \"\\n\" \"|\" | head -c 200"]}' \
        --region "${AWS_REGION}" --query "Command.CommandId" --output text 2>/dev/null || echo "")
      if [[ -n "$tail_id" ]]; then
        local _ts="InProgress" _tw=0
        while [[ "$_ts" == "InProgress" || "$_ts" == "Pending" ]]; do
          sleep 3; _tw=$((_tw+3)); [[ $_tw -ge 20 ]] && break
          _ts=$(aws ssm get-command-invocation --command-id "${tail_id}" --instance-id "${EC2_INSTANCE}" \
            --region "${AWS_REGION}" --query "Status" --output text 2>/dev/null || echo "Pending")
        done
      fi
      local tail=""
      [[ -n "$tail_id" ]] && tail=$(aws ssm get-command-invocation \
        --command-id "${tail_id}" --instance-id "${EC2_INSTANCE}" \
        --region "${AWS_REGION}" --query "StandardOutputContent" --output text 2>/dev/null | head -c 200)
      log "  ${elapsed}s — building | ${tail}"
    fi
  done
  fail "Build timed out after 30 min — check EC2: tail /tmp/axerp-deploy-run.log"
}

# ── Preflight ─────────────────────────────────────────────────────────────────
log "Preflight..."
command -v aws >/dev/null 2>&1 || fail "aws CLI not found"
command -v gh  >/dev/null 2>&1 || fail "gh CLI not found"
command -v git >/dev/null 2>&1 || fail "git not found"

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "${REPO_ROOT}"

CURRENT_BRANCH=$(git branch --show-current)
[[ "$CURRENT_BRANCH" != "production" ]] && warn "On branch ${CURRENT_BRANCH} — packaging origin/${CURRENT_BRANCH}"

# Detect image tag from the compose file (source of truth for what gets deployed),
# falling back to the Dockerfile build comment. Reading the compose file avoids
# the freeform-comment parsing fragility that produced wrong tags silently.
_COMPOSE_TAG=$(grep 'image:.*dkr\.ecr.*axerp:' "${COMPOSE_LOCAL}" | head -1 | \
  sed -E 's|.*axerp:([^ ]+).*|\1|' | grep -v "^$" || echo "")
if [[ -n "$_COMPOSE_TAG" ]]; then
  IMAGE_TAG="axerp:${_COMPOSE_TAG}"
else
  # Fallback: parse Dockerfile build comment
  IMAGE_TAG=$(grep "axerp:v" docker/Dockerfile | grep -v "^#.*ARG" | head -1 | \
    sed -E 's/.*-t (axerp:v[^ ]+).*/\1/' | grep -v "^$" || echo "")
  [[ -z "$IMAGE_TAG" ]] && IMAGE_TAG="axerp:$(grep '^ARG ERPNEXT_VERSION=' docker/Dockerfile | cut -d= -f2)-axerp.1"
fi
ECR_IMAGE="${ECR_REPO}:${IMAGE_TAG#axerp:}"
ECR_IMAGE_PROD="${ECR_REPO}:prod"

log "Image tag:  ${IMAGE_TAG}"
log "ECR image:  ${ECR_IMAGE}"
log "Site:       ${SITE}"
log "EC2:        ${EC2_INSTANCE}"
$DRY_RUN && warn "DRY RUN — no changes"
echo ""

# ── Step 1: Package the branch being deployed ────────────────────────────────
log "Step 1/7 — Package origin/${CURRENT_BRANCH} → S3"

# Always fetch first — without this, git archive uses a stale cached local ref
# (the known production failure: tarball packaged the pre-merge Dockerfile)
run git fetch origin "${CURRENT_BRANCH}"
run git archive "origin/${CURRENT_BRANCH}" \
  --format=tar.gz -o /tmp/axerp-production.tar.gz --prefix=axerp/

log "  Tarball: $(du -sh /tmp/axerp-production.tar.gz 2>/dev/null | cut -f1)"
run aws s3 cp /tmp/axerp-production.tar.gz \
  "s3://${S3_BUCKET}/${S3_PREFIX}/axerp-production.tar.gz" --quiet

[[ -f "${COMPOSE_LOCAL}" ]] && \
  run aws s3 cp "${COMPOSE_LOCAL}" \
    "s3://${S3_BUCKET}/${S3_PREFIX}/docker-compose.axerp.yml" --quiet && \
  ok "Compose uploaded" || warn "Compose not found at ${COMPOSE_LOCAL}"

ok "Step 1 complete"
echo ""

# ── Step 2: Generate build script ─────────────────────────────────────────────
log "Step 2/7 — Generate build + launcher scripts"

# Main build script — runs on EC2, builds image, pushes to ECR, deploys
cat > /tmp/axerp-deploy-run.sh << EOBUILD
#!/bin/bash
set -e
IMAGE_TAG="${IMAGE_TAG}"
ECR_IMAGE="${ECR_IMAGE}"
ECR_IMAGE_PROD="${ECR_IMAGE_PROD}"
ECR_REGISTRY="${ECR_REGISTRY}"
SITE="${SITE}"
AWS_REGION="${AWS_REGION}"
S3_BUCKET="${S3_BUCKET}"
S3_PREFIX="${S3_PREFIX}"

echo "[1] Fetch source + compose from S3..."
aws s3 cp s3://\${S3_BUCKET}/\${S3_PREFIX}/axerp-production.tar.gz /tmp/axerp-production.tar.gz --quiet
aws s3 cp s3://\${S3_BUCKET}/\${S3_PREFIX}/docker-compose.axerp.yml /opt/openproject/docker-compose.axerp.yml --quiet
echo "  tarball: \$(du -sh /tmp/axerp-production.tar.gz | cut -f1)"

echo "[2] Extract source..."
rm -rf /tmp/axerp-build && mkdir -p /tmp/axerp-build
tar -xzf /tmp/axerp-production.tar.gz -C /tmp/axerp-build --strip-components=1

echo "[3] ECR login..."
aws ecr get-login-password --region \${AWS_REGION} | \
  docker login --username AWS --password-stdin \${ECR_REGISTRY}

echo "[4] Build \${IMAGE_TAG} (arm64, no-cache)..."
echo "  start: \$(date -u +%H:%M:%S)"
cd /tmp/axerp-build
docker build \\
  --platform linux/arm64 \\
  --no-cache \\
  -f docker/Dockerfile \\
  -t \${IMAGE_TAG} \\
  -t axerp:prod \\
  -t \${ECR_IMAGE} \\
  -t \${ECR_IMAGE_PROD} \\
  . > /tmp/docker-build.log 2>&1
BUILD_EXIT=\$?
echo "  end:   \$(date -u +%H:%M:%S) | exit: \${BUILD_EXIT}"
if [ \${BUILD_EXIT} -ne 0 ]; then
  echo "BUILD FAILED — last 40 lines:"
  tail -40 /tmp/docker-build.log
  exit 1
fi
echo "  \$(tail -1 /tmp/docker-build.log)"

echo "[5] Push to ECR..."
docker push \${ECR_IMAGE}
docker push \${ECR_IMAGE_PROD}
echo "  Pushed: \${ECR_IMAGE}"

echo "[6] Update compose image tag to ECR URI..."
# Pattern matches both ECR URI format and bare local tag format
sed -i "s|image:.*axerp:.*|image: \${ECR_IMAGE}|g" /opt/openproject/docker-compose.axerp.yml
grep "image:.*axerp" /opt/openproject/docker-compose.axerp.yml | head -1 | xargs echo "  compose image now:"

echo "[7] Deploy stack..."
cd /opt/openproject
docker compose -f docker-compose.axerp.yml up -d 2>&1 | grep -vE "^(Pulling|pulled)" | head -30

echo "[9] Wait 25s for containers..."
sleep 25
docker ps --filter "name=axerp" --format "  {{.Names}} | {{.Status}}" | sort

echo "[10] Wait for migrate to complete..."
# Wait for container to exist and reach running/exited state before polling.
# Using status=running alone misses the brief 'created' state — if polled then,
# the loop exits immediately with docker inspect returning ExitCode=0 (unstarted default).
MIGRATE_DEADLINE=\$(( \$(date +%s) + 600 ))
# First wait for migrate to appear in any state
for _ in \$(seq 1 12); do
  docker ps -a --filter "name=axerp-migrate" --format "{{.Names}}" 2>/dev/null | grep -q axerp-migrate && break
  sleep 5
done
# Then wait for it to finish (leave running/created states)
while docker ps -a --filter "name=axerp-migrate" \
  --filter "status=running" --filter "status=created" \
  --format "{{.Names}}" 2>/dev/null | grep -q axerp-migrate; do
  [ \$(date +%s) -gt \${MIGRATE_DEADLINE} ] && { echo "  WARN: migrate timeout"; break; }
  sleep 10
done
MIGRATE_EXIT=\$(docker inspect axerp-migrate --format "{{.State.ExitCode}}" 2>/dev/null || echo "?")
echo "  migrate exit: \${MIGRATE_EXIT}"
docker logs axerp-migrate 2>&1 | tail -15
if [ "\${MIGRATE_EXIT}" != "0" ] && [ "\${MIGRATE_EXIT}" != "?" ]; then
  echo "ERROR: migration failed — check: docker logs axerp-migrate"
  exit 1
fi

echo "[11] Asset fix..."
aws s3 cp s3://\${S3_BUCKET}/\${S3_PREFIX}/axerp-fix-assets-json.sh /tmp/axerp-fix-assets-json.sh --quiet
SITE=\${SITE} bash /tmp/axerp-fix-assets-json.sh

echo "[12] Post-deploy cleanup checks..."
# a) Remove 'Delete Demo Data' navbar item if present (causes GET /undefined 404)
#    ERPNext may load this via migrations — it has no icon so add_app_item renders src="undefined"
DB_NAME=\$(docker exec axerp-backend python3 -c \
  "import json; c=json.load(open('/home/frappe/frappe-bench/sites/\${SITE}/site_config.json')); print(c['db_name'])" 2>/dev/null)
DB_PASS=\$(docker exec axerp-backend python3 -c \
  "import json; c=json.load(open('/home/frappe/frappe-bench/sites/\${SITE}/site_config.json')); print(c['db_password'])" 2>/dev/null)
if [ -n "\$DB_NAME" ]; then
  DEMO_COUNT=\$(docker exec axerp-mariadb mysql -u "\$DB_NAME" -p"\$DB_PASS" "\$DB_NAME" \
    -sN -e "SELECT COUNT(*) FROM \`tabNavbar Item\` WHERE parentfield='settings_dropdown' AND item_label='Delete Demo Data';" 2>/dev/null || echo "0")
  if [ "\$DEMO_COUNT" != "0" ] && [ "\$DEMO_COUNT" != "" ]; then
    docker exec axerp-mariadb mysql -u "\$DB_NAME" -p"\$DB_PASS" "\$DB_NAME" \
      -e "DELETE FROM \`tabNavbar Item\` WHERE parentfield='settings_dropdown' AND item_label='Delete Demo Data';" 2>/dev/null
    echo "  Removed 'Delete Demo Data' navbar item (was causing GET /undefined 404)"
  else
    echo "  Navbar items: OK (no icon-less demo items found)"
  fi
fi

# b) Flush Redis boot cache — prevents stale frappe.boot.sitename causing socket.io 'Invalid namespace'
docker exec axerp-redis-cache redis-cli FLUSHALL > /dev/null 2>&1
docker exec axerp-redis-queue redis-cli FLUSHALL > /dev/null 2>&1
docker exec axerp-backend bench --site \${SITE} clear-cache 2>&1 | tail -1
echo "  Redis boot cache flushed (prevents socket.io Invalid namespace on first login)"

echo "[13] Ping..."
CODE=\$(curl -sk -o /dev/null -w "%{http_code}" "https://\${SITE}/api/method/ping")
[ "\${CODE}" = "200" ] && echo "  PASS: \${SITE} 200" || echo "  WARN: \${SITE} returned \${CODE}"

echo "[14] Clean old local images (keep 3 most recent, remove the rest)..."
# Dynamic cleanup — never hardcodes tags, so can't accidentally delete an active image.
# Sort by creation date, keep the 3 newest, remove the rest.
OLD_IMAGES=\$(docker images axerp --format "{{.CreatedAt}}\t{{.Repository}}:{{.Tag}}" 2>/dev/null | \
  grep -v "<none>" | sort -r | awk 'NR>3 {print \$2}')
for OLD in \${OLD_IMAGES}; do
  docker rmi "\${OLD}" 2>/dev/null && echo "  Removed \${OLD}" || true
done
docker images axerp --format "  {{.Repository}}:{{.Tag}} | {{.Size}}"

echo "=== DEPLOY COMPLETE ==="
EOBUILD

# Launcher — runs build script in background subshell, writes exit code to status file
cat > /tmp/axerp-launch.sh << 'EOLAUNCH'
#!/bin/bash
rm -f /tmp/axerp-deploy-status /tmp/axerp-deploy-run.log
(
  bash /tmp/axerp-deploy-run.sh > /tmp/axerp-deploy-run.log 2>&1
  echo $? > /tmp/axerp-deploy-status
) &
BGPID=$!
echo "Launched build PID $BGPID"
disown $BGPID
EOLAUNCH

if ! $DRY_RUN; then
  aws s3 cp /tmp/axerp-deploy-run.sh "s3://${S3_BUCKET}/${S3_PREFIX}/axerp-deploy-run.sh" --quiet
  aws s3 cp /tmp/axerp-launch.sh "s3://${S3_BUCKET}/${S3_PREFIX}/axerp-launch.sh" --quiet
fi
ok "Step 2 complete"
echo ""

# ── Step 3: Build + push on EC2 ───────────────────────────────────────────────
if $SKIP_BUILD; then
  warn "Step 3/7 — Skipped (--skip-build)"
else
  # Keep pkill in its own command. Wrapping it in bash -lc together with the
  # s3 paths puts axerp-deploy-run.sh in that bash argv, and pkill SIGTERMs
  # itself (SSM exit 143, "Terminated").
  ssm_run "Step 3a/7 — Stage scripts on EC2 (kill stale builds first)" \
    "pkill -f '[a]xerp-deploy-run.sh' >/dev/null 2>&1 || true" \
    "echo Killed stale builds" \
    "aws s3 cp s3://${S3_BUCKET}/${S3_PREFIX}/axerp-deploy-run.sh /tmp/axerp-deploy-run.sh" \
    "aws s3 cp s3://${S3_BUCKET}/${S3_PREFIX}/axerp-launch.sh /tmp/axerp-launch.sh" \
    "chmod +x /tmp/axerp-deploy-run.sh /tmp/axerp-launch.sh" \
    "rm -f /tmp/axerp-deploy-status /tmp/axerp-deploy-run.log" \
    "test -s /tmp/axerp-launch.sh && echo STAGED"

  ssm_run "Step 3b/7 — Launch background build" \
    "bash /tmp/axerp-launch.sh" \
    "sleep 5" \
    "if pgrep -f '[a]xerp-deploy-run.sh' > /dev/null; then echo BUILD_RUNNING; else echo LAUNCH_FAILED && exit 1; fi"

  if ! $DRY_RUN; then
    poll_background_build
    # Show final log tail
    FINAL_LOG_ID=$(aws ssm send-command \
      --instance-ids "${EC2_INSTANCE}" --document-name "AWS-RunShellScript" \
      --parameters '{"commands":["tail -30 /tmp/axerp-deploy-run.log"]}' \
      --region "${AWS_REGION}" --query "Command.CommandId" --output text)
    _fs="InProgress"; _fw=0
    while [[ "$_fs" == "InProgress" || "$_fs" == "Pending" ]]; do
      sleep 3; _fw=$((_fw+3))
      _fs=$(aws ssm get-command-invocation --command-id "${FINAL_LOG_ID}" --instance-id "${EC2_INSTANCE}" \
        --region "${AWS_REGION}" --query "Status" --output text 2>/dev/null || echo "Pending")
      [[ $_fw -ge 30 ]] && break
    done
    echo "── EC2 deploy log (tail) ────────────────────────────"
    aws ssm get-command-invocation \
      --command-id "${FINAL_LOG_ID}" --instance-id "${EC2_INSTANCE}" \
      --region "${AWS_REGION}" --query "StandardOutputContent" --output text 2>/dev/null
    echo "────────────────────────────────────────────────────"
  fi
fi
ok "Step 3 complete"
echo ""

# ── Step 4: External health checks ───────────────────────────────────────────
log "Step 4/7 — External health checks"
CHECKS_PASSED=0; CHECKS_FAILED=0

check_url() {
  local label="$1" url="$2" expected="${3:-200}"
  if $DRY_RUN; then echo "  [dry-run] check: ${label}"; return; fi
  local code
  code=$(curl -sk -o /dev/null -w "%{http_code}" --max-time 10 "${url}" 2>/dev/null || echo "000")
  if [[ "$code" == "$expected" ]]; then
    ok "  ${label}: ${code}"; CHECKS_PASSED=$((CHECKS_PASSED + 1))
  else
    warn "  ${label}: ${code} (expected ${expected})"; CHECKS_FAILED=$((CHECKS_FAILED + 1))
  fi
}

check_url "ping"       "https://${SITE}/api/method/ping"
check_url "login page" "https://${SITE}/login"
check_url "desk"       "https://${SITE}/app" "302"

# App logo files — missing logos cause GET /undefined 404 in sidebar
# (discovered in v16.26.2: fix-assets script syncs them from backend→frontend)
for LOGO_PATH in \
  "/assets/erpnext/images/erpnext-logo.svg" \
  "/assets/hrms/images/frappe-hr-logo.svg" \
  "/assets/crm/images/logo.svg" \
  "/assets/insights/frontend/insights-logo.png" \
  "/assets/wiki/images/wiki-logo.png" \
  "/assets/blog/blog.svg"; do
  check_url "logo: $(basename $LOGO_PATH)" "https://${SITE}${LOGO_PATH}"
done

echo ""
log "Health checks: ${CHECKS_PASSED} passed / ${CHECKS_FAILED} failed"
[[ $CHECKS_FAILED -gt 0 ]] && warn "Some checks failed — re-run: bash scripts/deploy.sh --skip-build"

# ── Step 5: ECR image verification ────────────────────────────────────────────
log "Step 5/7 — Verify ECR image pushed"
if ! $DRY_RUN; then
  aws ecr describe-images \
    --repository-name axerp \
    --region "${AWS_REGION}" \
    --query "sort_by(imageDetails, &imagePushedAt)[-3:] | reverse(@) | \
      [].{tag: imageTag[0], pushed: imagePushedAt, size: imageSizeInBytes}" \
    --output table 2>/dev/null || warn "Could not query ECR"
fi

# ── Step 6: GitHub release ────────────────────────────────────────────────────
log "Step 6/7 — Create GitHub release for ${IMAGE_TAG}"
if ! $DRY_RUN; then
  # Only create if no release exists for this tag
  EXISTING=$(gh api "repos/axinagroup/axerp/releases/tags/${IMAGE_TAG#axerp:}" \
    --jq '.tag_name' 2>/dev/null || echo "")
  if [[ -z "$EXISTING" ]]; then
    ERPNEXT_VER=$(grep '^ARG ERPNEXT_VERSION=' docker/Dockerfile | cut -d= -f2)
    gh release create "${IMAGE_TAG#axerp:}" \
      --repo axinagroup/axerp \
      --title "AXERP ${IMAGE_TAG#axerp:}" \
      --notes "## ${IMAGE_TAG}

Built from upstream ERPNext ${ERPNEXT_VER} with AXERP branding.
ECR: \`${ECR_IMAGE}\`

### Apps
- frappe (base image ${ERPNEXT_VER})
- erpnext/AXERP (production branch)
- hrms (version-16)
- crm (main)
- insights (develop)
- wiki (version-3)
- blog (develop)" \
      --latest
    ok "GitHub release created: ${IMAGE_TAG#axerp:}"
  else
    log "  Release already exists for ${IMAGE_TAG#axerp:}"
  fi
fi

# ── Step 7: Summary ───────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════════════════"
if $DRY_RUN; then
  echo "  DRY RUN complete"
else
  echo "  DEPLOY COMPLETE"
  echo "  Image:  ${IMAGE_TAG}"
  echo "  ECR:    ${ECR_IMAGE}"
  echo "  Site:   https://${SITE}"
  echo "  Checks: ${CHECKS_PASSED} passed / ${CHECKS_FAILED} failed"
fi
echo "══════════════════════════════════════════════════════════"
