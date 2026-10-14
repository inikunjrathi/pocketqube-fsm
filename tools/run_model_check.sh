#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JAR="$REPO_ROOT/tools/vendor/tla2tools.jar"
SPEC_DIR="$REPO_ROOT/docs/tla"

if [[ ! -f "$JAR" ]]; then
  echo "error: $JAR not found. Download it with: mkdir -p tools/vendor && curl -sL -o tools/vendor/tla2tools.jar https://github.com/tlaplus/tlaplus/releases/latest/download/tla2tools.jar" >&2
  exit 1
fi
if ! command -v java >/dev/null 2>&1; then
  echo "error: java not found on PATH -- TLC requires a JVM." >&2
  exit 1
fi

echo "Regenerating docs/tla/*.tla and *.cfg..."
"$REPO_ROOT/.venv/bin/python" -m tools.generate_tla_spec

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

status=0
for module in config_a config_b config_c; do
  echo ""
  echo "=== TLC: $module ==="
  if ! (cd "$SPEC_DIR" && java -cp "$JAR" tlc2.TLC -metadir "$tmp/$module" \
        -config "$module.cfg" "$module.tla"); then
    status=1
  fi

  for latch in $(sed -n 's/^PROPERTY \(.*\)DurableNeverClears$/\1/p' "$SPEC_DIR/$module.cfg"); do
    printf 'SPECIFICATION Spec\nPROPERTY %sNeverClears\n' "$latch" > "$tmp/$module-ram.cfg"
    echo "--- $module: in-RAM ${latch}NeverClears (expected: violated) ---"
    (cd "$SPEC_DIR" && java -cp "$JAR" tlc2.TLC -metadir "$tmp/$module-ram" \
        -config "$tmp/$module-ram.cfg" "$module.tla") > "$tmp/$module-ram.out" 2>&1 || true
    if grep -q "is violated" "$tmp/$module-ram.out"; then
      echo "ok: counterexample found (torn save of the latch-setting step, then RESET)"
    else
      echo "UNEXPECTED: in-RAM ${latch}NeverClears holds -- persistence model is vacuous?" >&2
      status=1
    fi
  done
done

echo ""
if [[ "$status" -ne 0 ]]; then
  echo "One or more checks failed -- see output above." >&2
else
  echo "All configs: no error found."
fi
exit "$status"
