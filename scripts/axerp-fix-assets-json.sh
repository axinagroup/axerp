#!/bin/bash
# AXERP post-deploy asset fix — run after every redeploy.
#
# What this does:
#   1. bench build --production  → rebuilds ALL app JS/CSS bundles with correct
#      content hashes and regenerates assets.json. This is the definitive fix for
#      CSS/icon issues — per-app builds can leave stale hashes for other apps.
#   2. docker cp all app assets (frappe/erpnext/hrms/crm/insights/wiki/blog)
#      from backend → frontend so nginx serves the freshly-built files.
#   3. nginx reload, Redis + Frappe cache flush.
#   4. HTTP verify every bundle in assets.json returns 200.
#
# Why bench build --production instead of per-app:
#   --production rebuilds all apps in one pass, recalculates all content hashes,
#   and writes a complete assets.json. Per-app builds only update that app's hashes
#   in assets.json, which can leave the file out of sync with the frontend files
#   already on disk for other apps — causing 404s and icon mismatches.

set -e
BENCH=/home/frappe/frappe-bench
BAKED=${BENCH}/assets
SITE=${SITE:-erp.tspgusa.com}

echo "=== [1] bench build --production (rebuild ALL app bundles + regenerate assets.json) ==="
echo "    This fixes CSS/icon mismatches caused by stale per-app hash divergence."
docker exec axerp-backend bash -c "cd ${BENCH} && bench build --production 2>&1" | \
  grep -E "(Done in|Building|Linking|error|WARN|✔)" | tail -10
echo ""

echo "=== [2] Show resulting assets.json ==="
docker exec axerp-backend python3 -c "
import json
with open('${BAKED}/assets.json') as f:
    d = json.load(f)
print(f'Total entries: {len(d)}')
for k,v in sorted(d.items()):
    print(f'  {k}: {v}')
" 2>/dev/null
echo ""

echo "=== [2b] Insights islands (chart + dashboard embeds) ==="
docker exec -u frappe -w /home/frappe/frappe-bench/apps/insights/frontend axerp-backend \
  yarn build:islands --production
echo ""

echo "=== [3] Sync all app assets from backend to frontend ==="
for APP in frappe erpnext hrms crm insights wiki blog; do
  rm -rf /tmp/${APP}-assets && mkdir -p /tmp/${APP}-assets
  docker cp axerp-backend:${BAKED}/${APP}/. /tmp/${APP}-assets/ 2>/dev/null \
    || { echo "  SKIP ${APP} (not in backend BAKED_PATH)"; continue; }
  docker cp /tmp/${APP}-assets/. axerp-frontend:${BAKED}/${APP}/
  TOTAL=$(docker exec axerp-frontend find ${BAKED}/${APP} -type f 2>/dev/null | wc -l)
  echo "  ${APP}: ${TOTAL} files synced to frontend"
done
echo ""

echo "=== [4] Copy assets.json + assets-rtl.json to frontend ==="
docker cp axerp-backend:${BAKED}/assets.json /tmp/assets.json
docker cp /tmp/assets.json axerp-frontend:${BAKED}/assets.json
docker cp axerp-backend:${BAKED}/assets-rtl.json /tmp/assets-rtl.json 2>/dev/null \
  && docker cp /tmp/assets-rtl.json axerp-frontend:${BAKED}/assets-rtl.json \
  || echo "  assets-rtl.json not found -- skipping"
echo "  Copied"
echo ""

echo "=== [5] nginx reload ==="
docker exec axerp-frontend nginx -s reload 2>&1
echo ""

echo "=== [6] Clear all Frappe caches ==="
docker exec axerp-redis-cache redis-cli FLUSHALL 2>&1
docker exec axerp-backend bench --site ${SITE} clear-cache 2>&1 | tail -1
docker exec axerp-backend bench --site ${SITE} clear-website-cache 2>&1 | tail -1
echo ""

echo "=== [7] HTTP check every bundle in assets.json ==="
FIP=$(docker inspect axerp-frontend \
  --format "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}" | awk '{print $1}')
echo "  Frontend IP: ${FIP}"

FAILS=0
TOTAL=0
while IFS=":" read -r KEY VAL; do
  VAL=$(echo "${VAL}" | tr -d ' "')
  [ -z "${VAL}" ] && continue
  CODE=$(curl -sk -o /dev/null -w "%{http_code}" --max-time 5 "http://${FIP}:8080${VAL}")
  TOTAL=$((TOTAL+1))
  if [ "${CODE}" != "200" ]; then
    echo "  FAIL ${CODE}  ${KEY} => ${VAL}"
    FAILS=$((FAILS+1))
  fi
done < <(docker exec axerp-backend python3 -c "
import json
with open('${BAKED}/assets.json') as f:
    d = json.load(f)
for k,v in d.items():
    print(f'{k}:{v}')
" 2>/dev/null)

echo "  Checked ${TOTAL} bundles: ${FAILS} failures"
if [ ${FAILS} -gt 0 ]; then
  echo "  WARNING: Some bundles failed -- check output above"
else
  echo "  OK: All bundles serving 200"
fi
echo ""

echo "=== [8] Spot-check critical login/desk bundles ==="
for BUNDLE in login.bundle.css desk.bundle.css libs.bundle.js desk.bundle.js website.bundle.css frappe-web.bundle.js; do
  PATH_VAL=$(docker exec axerp-backend python3 -c "
import json
with open('${BAKED}/assets.json') as f: d=json.load(f)
print(d.get('${BUNDLE}','NOT_IN_JSON'))
" 2>/dev/null)
  if [ "${PATH_VAL}" = "NOT_IN_JSON" ]; then
    echo "  MISSING: ${BUNDLE}"
  else
    CODE=$(curl -sk -o /dev/null -w "%{http_code}" --max-time 5 "http://${FIP}:8080${PATH_VAL}")
    if [ "${CODE}" = "200" ]; then
      echo "  PASS ${BUNDLE}: ${CODE}"
    else
      echo "  FAIL ${BUNDLE}: ${CODE}"
    fi
  fi
done
echo ""

echo "=== [9] Ping site ==="
CODE=$(curl -sk -o /dev/null -w "%{http_code}" --max-time 10 "https://${SITE}/api/method/ping" 2>/dev/null || echo "000")
if [ "${CODE}" = "200" ]; then
  echo "  PASS: https://${SITE} returned 200"
else
  echo "  WARN: https://${SITE} returned ${CODE} (may still be warming up)"
fi

echo ""
echo "=== DONE ==="
