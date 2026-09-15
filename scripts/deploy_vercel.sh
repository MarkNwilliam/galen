#!/usr/bin/env bash
# Deploy the Galen frontend to Vercel as a public demo.
#
# Why this is a script: Vercel's `/v9/projects` API defaults every newly created
# project to SSO-protected deployments (`all_except_custom_domains`), so a fresh
# `vercel --prod` upload is hidden behind the SSO "Redirecting..." wall. After
# every deploy we PATCH `ssoProtection: null` on the project that got created,
# then re-point the stable `galen-kb.vercel.app` alias at the fresh deployment.
set -euo pipefail
cd "$(dirname "$0")/../ui"
PROJECT="galen-app"
ALIAS="galen-kb.vercel.app"
TOKEN_JSON="$HOME/Library/Application Support/com.vercel.cli/auth.json"
TEAM="team_n7QCqV07mFOg8O0Hmg4zlyYP"

TOKEN="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])))['token']" "$TOKEN_JSON")"

# 1) Fresh deploy (deterministic project name, no stale link state).
rm -rf .vercel
OUTPUT="$(vercel --prod --yes --name "$PROJECT" --cwd "$(pwd)")"
echo "$OUTPUT"
DEPLOY_URL="$(printf '%s\n' "$OUTPUT" | rg -o 'https://[a-z0-9-]+-[a-z0-9]+-nkugwa-mark-williams-projects\.vercel\.app' | head -1)"
[ -n "$DEPLOY_URL" ] || { echo "could not parse deployment URL"; exit 1; }
echo "deployment: $DEPLOY_URL"

# 2) Make it public on the API.
PROJECT_ID="$(curl -s -H "Authorization: Bearer $TOKEN" "https://api.vercel.com/v9/projects?teamId=$TEAM" |
  python3 -c "import sys,json; print(next(x['id'] for x in json.load(sys.stdin)['projects'] if x['name']=='$PROJECT'))")"
curl -s -X PATCH -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  "https://api.vercel.com/v9/projects/$PROJECT_ID?teamId=$TEAM" -d '{"ssoProtection": null}' >/dev/null
echo "made public (ssoProtection: null)"

# 3) Point the stable alias at the new deployment.
vercel alias set "$DEPLOY_URL" "$ALIAS"

echo
echo "LIVE: https://$ALIAS"