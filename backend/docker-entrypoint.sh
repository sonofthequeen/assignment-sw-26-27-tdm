#!/bin/sh
# Container start: apply migrations, optionally load the synthetic demo data,
# then hand over to the server command (CMD).
set -eu

echo "Applying database migrations…"
alembic upgrade head

if [ "${SEED_DEMO_DATA:-false}" = "true" ]; then
  # Idempotent: writes nothing if the demo dataset is already present.
  python -m scripts.seed
fi

exec "$@"
