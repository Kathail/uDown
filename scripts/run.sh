#!/usr/bin/env bash
# udown launcher — pulls the latest image, generates credentials on first run,
# starts the container, prints the local URL and password.
set -euo pipefail

IMAGE="ghcr.io/kathail/udown:latest"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/udown"
ENV_FILE="$DATA_DIR/env"
PORT="${UDOWN_PORT:-8000}"

mkdir -p "$DATA_DIR"
chmod 700 "$DATA_DIR"

if [ ! -f "$ENV_FILE" ]; then
    pw=$(LC_ALL=C tr -dc 'a-z0-9' </dev/urandom | head -c 16)
    secret=$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 48)
    umask 077
    {
        printf 'APP_PASSWORD=%s\n' "$pw"
        printf 'SESSION_SECRET=%s\n' "$secret"
    } > "$ENV_FILE"
    echo "generated credentials at $ENV_FILE"
fi

password=$(grep '^APP_PASSWORD=' "$ENV_FILE" | cut -d= -f2-)

echo "==========================================="
echo "  udown → http://localhost:$PORT"
echo "  password: $password"
echo "==========================================="

docker pull "$IMAGE" >/dev/null

exec docker run --rm -it \
    -p "${PORT}:8000" \
    --env-file "$ENV_FILE" \
    --name udown \
    "$IMAGE"
