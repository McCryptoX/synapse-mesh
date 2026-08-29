#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir"

if command -v npx >/dev/null 2>&1; then
    exec npx --yes tailwindcss@3.4.17 \
        --config tailwind.config.js \
        --input app/static/tailwind.input.css \
        --output app/static/style.min.css \
        --minify
fi

if command -v pnpm >/dev/null 2>&1; then
    exec pnpm dlx tailwindcss@3.4.17 \
        --config tailwind.config.js \
        --input app/static/tailwind.input.css \
        --output app/static/style.min.css \
        --minify
fi

echo "A Node.js package runner (npx or pnpm) is required." >&2
exit 1
