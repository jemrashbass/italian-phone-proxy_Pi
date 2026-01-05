#!/usr/bin/env bash

set -euo pipefail

# ---- configuration ----
SRC_ROOT="app"                 # root to scan
DEST_DIR="flattened_export"    # output directory
TIMESTAMP="$(date +%Y%m%d-%H%M)"

# ---- setup ----
mkdir -p "$DEST_DIR"

echo "Flattening files from '$SRC_ROOT' into '$DEST_DIR'"
echo "Timestamp: $TIMESTAMP"
echo

# ---- main loop ----
find "$SRC_ROOT" -type f | while read -r filepath; do
    filename="$(basename "$filepath")"
    parentdir="$(basename "$(dirname "$filepath")")"

    # split filename into name + extension
    base="${filename%.*}"
    ext="${filename##*.}"

    if [[ "$filename" == "$ext" ]]; then
        # no extension
        newname="${base}_${parentdir}_${TIMESTAMP}"
    else
        newname="${base}_${parentdir}_${TIMESTAMP}.${ext}"
    fi

    cp "$filepath" "$DEST_DIR/$newname"

    echo "✔ $filepath → $newname"
done

echo
echo "Done."