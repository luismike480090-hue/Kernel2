#!/usr/bin/env bash
set -euo pipefail

ROOTS=("$@")
if [ ${#ROOTS[@]} -eq 0 ]; then
  ROOTS=("kernel" "huawei-k3-reference")
fi

echo "===== HWT101 MISSING DRIVER AUDIT ====="
for R in "${ROOTS[@]}"; do
  [ -d "$R" ] || continue
  echo
  echo "### TREE: $R"

  for spec in \
    "GOODIX:goodix_ts_probe:goodix gt9 gt911 gt818" \
    "FT5X0X:ft5x0x_ts_probe:ft5 ft5206 ft5306 focaltech" \
    "GC0339:gc0339_init:gc0339" \
    "S5K5CAG:s5k5cag_init:s5k5cag"
  do
    IFS=: read -r name sym words <<<"$spec"
    echo "-- $name / symbol $sym"
    grep -RIl --include='*.c' --include='*.h' "$sym" "$R" 2>/dev/null | head -20 || true
    for w in $words; do
      find "$R" -type f \( -iname "*$w*.c" -o -iname "*$w*.h" \) 2>/dev/null | head -20 || true
    done
  done
done
