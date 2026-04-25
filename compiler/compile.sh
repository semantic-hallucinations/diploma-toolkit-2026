#!/usr/bin/env bash
set -euo pipefail

SRC_DIR="${1:-/workspace}"
OUT_DIR="${2:-/out}"
MAIN_TEX="${3:-diploma/diploma_report.tex}"
JOB_NAME="${4:-diploma_report}"

if [ ! -f "$SRC_DIR/$MAIN_TEX" ]; then
  printf 'Main TeX file not found: %s/%s\n' "$SRC_DIR" "$MAIN_TEX" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"
while IFS= read -r dir; do
  rel="${dir#"$SRC_DIR"}"
  mkdir -p "$OUT_DIR/$rel"
done < <(find "$SRC_DIR" -type d)

export HOME="${HOME:-/tmp}"
export BIBINPUTS="$SRC_DIR:"
export BSTINPUTS="$SRC_DIR:"

run_pdflatex() {
  local pass="$1"
  (
    cd "$SRC_DIR"
    pdflatex -interaction=nonstopmode -halt-on-error -output-directory "$OUT_DIR" "$MAIN_TEX"
  ) > "$OUT_DIR/pdflatex-$pass.log"
}

run_pdflatex 1
(
  cd "$OUT_DIR"
  bibtex "$JOB_NAME"
) > "$OUT_DIR/bibtex.log"
run_pdflatex 2
run_pdflatex 3

critical_pattern='No hyphenation patterns|Fatal error|^!|LaTeX Error|Package natbib Error|system returned with code|OSError|Citation .* undefined|There were undefined citations|undefined references'
if grep -E "$critical_pattern" "$OUT_DIR/pdflatex-3.log" "$OUT_DIR/bibtex.log" >/dev/null; then
  grep -E "$critical_pattern" "$OUT_DIR/pdflatex-3.log" "$OUT_DIR/bibtex.log" >&2
  exit 1
fi

printf '%s/%s.pdf\n' "$OUT_DIR" "$JOB_NAME"
