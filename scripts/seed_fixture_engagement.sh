#!/usr/bin/env bash
# Seed a fixture engagement with a small Excel TB so the UI has something
# to show. Requires the dev user from `make seed` and `curl` + `jq` locally.
set -euo pipefail

BASE="${API_BASE:-http://localhost:8080/api}"
EMAIL="${EMAIL:-dev@cpa.local}"
PASSWORD="${PASSWORD:-devpassword1234}"

token() {
  curl -fsS -X POST "${BASE}/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"email\": \"${EMAIL}\", \"password\": \"${PASSWORD}\"}" |
    jq -r '.tokens.access_token'
}

TOK="$(token)"
auth() { curl -fsS -H "Authorization: Bearer ${TOK}" "$@"; }

# Create / fetch client
CLIENT_ID="$(auth "${BASE}/clients" | jq -r '.[0].id // empty')"
if [ -z "${CLIENT_ID}" ]; then
  CLIENT_ID="$(auth -X POST "${BASE}/clients" -H 'Content-Type: application/json' \
    -d '{"name": "ACME Corporation", "jurisdiction": "US", "base_currency": "USD"}' \
    | jq -r '.id')"
fi
echo "client = ${CLIENT_ID}"

# Create engagement
ENG_ID="$(auth -X POST "${BASE}/engagements" -H 'Content-Type: application/json' \
  -d "{\"client_id\": \"${CLIENT_ID}\", \"name\": \"ACME 2024 Audit\", \"type\": \"audit\"}" \
  | jq -r '.id')"
echo "engagement = ${ENG_ID}"

# Import COA template
auth -X POST "${BASE}/engagements/${ENG_ID}/coa/import" -H 'Content-Type: application/json' \
  -d '{"template": "us_gaap"}' >/dev/null
echo "COA imported (us_gaap)"

echo "open http://localhost:8080/engagements/${ENG_ID}"
