#!/usr/bin/env bash

set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000/api}"
EMAIL="${EMAIL:-Erfan@gmail.com}"
PASSWORD="${PASSWORD:-changeme}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESPONSE_FILE="$SCRIPT_DIR/response.json"

PRETTY=0
GRADING_ID=""
LOGIN_BODY=""
TOKEN=""
DETAIL_BODY=""

usage() {
  cat <<'EOF'
Usage: scripts/test_grading_gets.sh [options]

Logs in with the configured credentials, fetches a bearer token, and runs
GET /api/gradings/{id}/ to fetch a grading run with full result payload.
The latest run is saved to scripts/response.json as pretty JSON.

Defaults:
  - Login with:
      EMAIL=Erfan@gmail.com
      PASSWORD=changeme
  - Call GET /api/gradings/

Options:
  --base-url URL    API base URL. Default: http://localhost:8000/api
  --email EMAIL     Login email. Default: Erfan@gmail.com
  --password PASS   Login password. Default: changeme
  --id UUID         Grading run id. If omitted, the first run from /gradings/ is used.
  --pretty          Pretty-print JSON responses
  -h, --help        Show this help

Examples:
  scripts/test_grading_gets.sh
  scripts/test_grading_gets.sh --id 11111111-2222-3333-4444-555555555555
  scripts/test_grading_gets.sh --pretty
EOF
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

print_json() {
  local body="$1"
  if [[ "$PRETTY" -eq 1 ]]; then
    python3 - "$body" <<'PY'
import json
import sys

payload = sys.argv[1]
try:
    data = json.loads(payload)
except json.JSONDecodeError:
    sys.stdout.write(payload)
    if payload and not payload.endswith("\n"):
        sys.stdout.write("\n")
    sys.exit(0)

print(json.dumps(data, indent=2, ensure_ascii=False))
PY
  else
    printf '%s\n' "$body"
  fi
}

print_section() {
  local title="$1"
  printf '\n[%s]\n' "$title"
}

write_response_file() {
  local temp_dir
  temp_dir="$(mktemp -d)"

  printf '%s' "$LOGIN_BODY" > "$temp_dir/login.json"
  printf '%s' "$DETAIL_BODY" > "$temp_dir/detail.json"

  python3 - \
    "$RESPONSE_FILE" \
    "$BASE_URL" \
    "$EMAIL" \
    "$GRADING_ID" \
    "$temp_dir/login.json" \
    "$temp_dir/detail.json" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone

(
    response_file,
    base_url,
    email,
    grading_id,
    login_path,
    detail_path,
) = sys.argv[1:]


def read_json(path):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


entry = {
    "executed_at": datetime.now(timezone.utc).isoformat(),
    "base_url": base_url,
    "email": email,
    "grading_id": grading_id,
    "responses": {
        "login": read_json(login_path),
        "detail": read_json(detail_path),
    },
}

with open(response_file, "w", encoding="utf-8") as fh:
    json.dump(entry, fh, indent=2, ensure_ascii=False)
    fh.write("\n")
PY

  rm -rf "$temp_dir"
}

extract_json_field() {
  local body="$1"
  local field="$2"
  python3 - "$body" "$field" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
field = sys.argv[2]
value = payload.get(field)
if value is None:
    sys.exit(1)
print(value)
PY
}

extract_first_grading_id() {
  local body="$1"
  python3 - "$body" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
if not isinstance(payload, list) or not payload:
    sys.exit(1)
grading_id = payload[0].get("id")
if not grading_id:
    sys.exit(1)
print(grading_id)
PY
}

request_json() {
  local method="$1"
  local url="$2"
  local token="$3"
  local body_file
  body_file="$(mktemp)"

  local http_code
  http_code="$(
    curl -sS \
      -X "$method" \
      -H "Authorization: Bearer $token" \
      -H "Accept: application/json" \
      -o "$body_file" \
      -w '%{http_code}' \
      "$url"
  )"

  local body
  body="$(cat "$body_file")"
  rm -f "$body_file"

  if [[ "$http_code" -lt 200 || "$http_code" -ge 300 ]]; then
    echo "Request failed: $method $url (HTTP $http_code)" >&2
    print_json "$body" >&2
    exit 1
  fi

  printf '%s' "$body"
}

login() {
  local login_url="$1/auth/login/"
  local payload
  payload="$(
    python3 - "$EMAIL" "$PASSWORD" <<'PY'
import json
import sys

print(json.dumps({"email": sys.argv[1], "password": sys.argv[2]}))
PY
  )"

  local body_file
  body_file="$(mktemp)"

  local http_code
  http_code="$(
    curl -sS \
      -X POST \
      -H "Content-Type: application/json" \
      -H "Accept: application/json" \
      -d "$payload" \
      -o "$body_file" \
      -w '%{http_code}' \
      "$login_url"
  )"

  local body
  body="$(cat "$body_file")"
  rm -f "$body_file"
  LOGIN_BODY="$body"

  if [[ "$http_code" -lt 200 || "$http_code" -ge 300 ]]; then
    echo "Login failed: $login_url (HTTP $http_code)" >&2
    print_json "$body" >&2
    exit 1
  fi

  TOKEN="$(extract_json_field "$body" "access_token")"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base-url)
      BASE_URL="$2"
      shift 2
      ;;
    --email)
      EMAIL="$2"
      shift 2
      ;;
    --password)
      PASSWORD="$2"
      shift 2
      ;;
    --id)
      GRADING_ID="$2"
      shift 2
      ;;
    --pretty)
      PRETTY=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

require_command curl
require_command python3

BASE_URL="${BASE_URL%/}"

login "$BASE_URL"

print_section "login"
print_json "$LOGIN_BODY"

if [[ -z "$GRADING_ID" ]]; then
  LIST_BODY="$(request_json GET "$BASE_URL/gradings/" "$TOKEN")"
  if ! GRADING_ID="$(extract_first_grading_id "$LIST_BODY")"; then
    echo "No grading runs found. Pass --id explicitly or create a grading run first." >&2
    exit 1
  fi
fi

DETAIL_BODY="$(request_json GET "$BASE_URL/gradings/$GRADING_ID/" "$TOKEN")"
print_section "GET /gradings/$GRADING_ID/"
print_json "$DETAIL_BODY"

write_response_file

print_section "saved"
printf '{"response_file":"%s"}\n' "$RESPONSE_FILE"
