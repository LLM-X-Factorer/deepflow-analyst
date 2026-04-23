#!/usr/bin/env bash
# Download the Chinook PostgreSQL seed SQL into data/seed/.
# The file is large (~2 MB) so we don't commit it; fetch on demand.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SEED_DIR="$REPO_ROOT/data/seed"
DEST="$SEED_DIR/01-chinook.sql"
SRC_URL="https://raw.githubusercontent.com/lerocha/chinook-database/master/ChinookDatabase/DataSources/Chinook_PostgreSql.sql"

mkdir -p "$SEED_DIR"

if [[ -f "$DEST" ]]; then
  echo "[chinook] already present: $DEST"
  exit 0
fi

echo "[chinook] fetching from $SRC_URL"
curl -fsSL "$SRC_URL" -o "$DEST.raw"

# Patch: upstream SQL creates its own "chinook" database and \c into it.
# We want everything loaded into the default database the init script connects to
# (i.e. the POSTGRES_DB defined in docker-compose).
sed -E '/^(DROP|CREATE) DATABASE chinook/d; /^\\c[[:space:]]+chinook/d' "$DEST.raw" > "$DEST"
rm "$DEST.raw"

echo "[chinook] wrote $DEST ($(wc -l <"$DEST") lines)"
