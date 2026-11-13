#!/usr/bin/env bash
# =============================================================================
# Runs ON the EC2 instance, sent by GitHub Actions through SSM Run Command.
#
#   1. log in to ECR (using the instance's IAM role, no stored credentials)
#   2. pull the new image
#   3. load secrets from SSM Parameter Store (/tripmate/*) into an env file
#   4. replace the running container
#   5. wait for /health; if it never goes healthy, roll back to the old image
#
# Required env vars: IMAGE_URI, AWS_REGION
# =============================================================================
set -euo pipefail

: "${IMAGE_URI:?IMAGE_URI is required}"
: "${AWS_REGION:?AWS_REGION is required}"

APP_NAME=tripmate
HOST_PORT=8000
ENV_DIR=/etc/tripmate
ENV_FILE="$ENV_DIR/app.env"
REGISTRY="${IMAGE_URI%%/*}"
HEALTH_URL="http://127.0.0.1:${HOST_PORT}/health"

echo "==> Logging in to ECR ($REGISTRY)"
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$REGISTRY"

echo "==> Pulling $IMAGE_URI"
docker pull "$IMAGE_URI"

echo "==> Loading secrets from Parameter Store (/tripmate/)"
install -d -m 700 "$ENV_DIR"
umask 077
# /tripmate/GROQ_API_KEY -> GROQ_API_KEY=<value>   (values are never printed)
# Leading/trailing whitespace is trimmed: a stray space pasted before
# "postgresql://" makes psycopg reject the whole connection string.
aws ssm get-parameters-by-path \
    --region "$AWS_REGION" --path /tripmate/ --with-decryption \
    --query 'Parameters[].[Name,Value]' --output text \
  | awk -F'\t' '{
      name = $1; sub("^/tripmate/", "", name)
      value = $2; gsub(/^[ \t\r]+|[ \t\r]+$/, "", value)
      print name "=" value
    }' \
  > "$ENV_FILE.new"
mv "$ENV_FILE.new" "$ENV_FILE"
echo "    loaded: $(cut -d= -f1 "$ENV_FILE" | tr '\n' ' ')"

start_container() {
  docker run -d \
    --name "$APP_NAME" \
    --restart unless-stopped \
    --env-file "$ENV_FILE" \
    -p "${HOST_PORT}:8000" \
    "$1" >/dev/null
}

wait_healthy() {
  for _ in $(seq 1 45); do              # up to ~90 seconds
    if curl -fsS --max-time 3 "$HEALTH_URL" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  return 1
}

PREVIOUS_IMAGE="$(docker inspect --format '{{.Config.Image}}' "$APP_NAME" 2>/dev/null || true)"
echo "==> Previous image: ${PREVIOUS_IMAGE:-<none>}"

echo "==> Starting new container"
docker rm -f "$APP_NAME" >/dev/null 2>&1 || true
start_container "$IMAGE_URI"

echo "==> Waiting for $HEALTH_URL"
if wait_healthy; then
  echo "==> Deploy OK: $IMAGE_URI is healthy"
  # Free disk: remove images not used by any container and older than 7 days.
  docker image prune -af --filter "until=168h" >/dev/null 2>&1 || true
  exit 0
fi

echo "!! New container did not become healthy. Last log lines:"
# Redact credentials in any connection string (scheme://user:password@host)
# before the logs reach SSM / GitHub output.
docker logs --tail 50 "$APP_NAME" 2>&1 \
  | sed -E 's#([a-zA-Z][a-zA-Z0-9+.-]*://)[^@/[:space:]]+@#\1***@#g' || true
docker rm -f "$APP_NAME" >/dev/null 2>&1 || true

if [ -n "$PREVIOUS_IMAGE" ] && [ "$PREVIOUS_IMAGE" != "$IMAGE_URI" ]; then
  echo "==> Rolling back to $PREVIOUS_IMAGE"
  start_container "$PREVIOUS_IMAGE"
  if wait_healthy; then
    echo "==> Rollback OK"
  else
    echo "!! Rollback image is also unhealthy"
  fi
fi
exit 1
