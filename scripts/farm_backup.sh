#!/usr/bin/env sh
# Daily backup of everything the farm cannot rebuild.
#
#   sh scripts/farm_backup.sh              # back up and upload
#   sh scripts/farm_backup.sh --no-upload  # build the archive only
#
# Losing the SQLite database loses every account's creation date, which resets
# the warming policy to day 1 — that is the whole reason this script exists.
#
# What goes in:
#   data/gitd.db            the ledger, the job queue, the outbox (.backup, WAL-safe)
#   ~/.ofmai/farm/phones.json  which phone is which character
#   .env                    KEYS ONLY, every value stripped
#   keychain-entries.txt    the NAMES of the ofmai-* Keychain entries, no values
#
# What never goes in: proxy credentials, account passwords, OAuth tokens. They
# live in the macOS Keychain and in Nathan's password manager, nowhere else (R9).
# Restoring is a manual, ordered procedure — see docs/social/architecture.md §7.
#
# NOT TESTABLE WITHOUT THE REAL MACHINE: the Keychain, the AWS credentials and
# the S3 bucket. Run it once by hand and check the object lands before trusting
# the schedule, then do a restore drill before the first real accounts exist.

set -u

cd "$(dirname "$0")/.." || exit 1

DAY=$(date +%Y-%m-%d)
BUCKET="${FARM_BACKUP_BUCKET:-s3://hiddn2/farm-backups}"
REGISTRY="${FARM_PHONES_JSON:-$HOME/.ofmai/farm/phones.json}"
DB="${FARM_DB:-data/gitd.db}"
STAGE=$(mktemp -d "/tmp/farm-backup-$DAY.XXXXXX") || exit 1
ARCHIVE="/tmp/$DAY.tar.gz"
UPLOAD=1
[ "${1:-}" = "--no-upload" ] && UPLOAD=0

cleanup() { rm -rf "$STAGE"; }
trap cleanup EXIT

# 1. the database — `.backup` is the only WAL-safe way to copy a live SQLite file
if [ -f "$DB" ]; then
  sqlite3 "$DB" ".backup '$STAGE/gitd.db'" || { echo "farm_backup: sqlite backup failed" >&2; exit 1; }
else
  echo "farm_backup: no database at $DB" >&2
  exit 1
fi

# 2. which phone is which character
[ -f "$REGISTRY" ] && cp "$REGISTRY" "$STAGE/phones.json"

# 3. the shape of the environment, never its contents
[ -f .env ] && sed 's/=.*/=/' .env > "$STAGE/env.keys"

# 4. the names of the Keychain entries, so a restore knows what is missing
if command -v security >/dev/null 2>&1; then
  security dump-keychain 2>/dev/null | grep -o 'ofmai-[a-z0-9.-]*' | sort -u > "$STAGE/keychain-entries.txt"
fi

tar -czf "$ARCHIVE" -C "$STAGE" . || { echo "farm_backup: tar failed" >&2; exit 1; }
echo "farm_backup: $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"

[ "$UPLOAD" = 0 ] && exit 0

# 5. upload with the dedicated IAM user (PutObject on this prefix and nothing else)
CREDS=$(security find-generic-password -s ofmai-aws-backup -w 2>/dev/null || echo "")
if [ -z "$CREDS" ]; then
  echo "farm_backup: no ofmai-aws-backup entry in the Keychain — archive kept at $ARCHIVE" >&2
  exit 1
fi
AWS_ACCESS_KEY_ID=$(echo "$CREDS" | cut -d: -f1)
AWS_SECRET_ACCESS_KEY=$(echo "$CREDS" | cut -d: -f2)
export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY

if aws s3 cp "$ARCHIVE" "$BUCKET/$DAY.tar.gz" >/dev/null; then
  echo "farm_backup: uploaded $BUCKET/$DAY.tar.gz"
  rm -f "$ARCHIVE"
else
  echo "farm_backup: upload failed — archive kept at $ARCHIVE" >&2
  exit 1
fi
# Retention is an S3 lifecycle rule on the prefix (14 days), not this script.
