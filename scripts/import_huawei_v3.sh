#!/usr/bin/env bash
set -euo pipefail
K="${1:-kernel}"
R="${2:-huawei-k3-reference}"
REPORT="${3:-DONOR-HARDWARE-INVENTORY.txt}"
: > "$REPORT"

say(){ echo "$*" | tee -a "$REPORT"; }
find_symbol_file(){
  local sym="$1"
  grep -RIl --include='*.c' --include='*.h' "$sym" "$R" 2>/dev/null | head -1 || true
}

say "HWT101 V3 donor import"
say "Base: $K"
say "Reference: $R"

# 1) Huawei BQ2419X: exact K3V2-era donor verified to exist in mangusta86 tree.
if [ -f "$R/drivers/power/bq2419x_charger.c" ]; then
  cp "$R/drivers/power/bq2419x_charger.c" "$K/drivers/power/bq2419x_charger.c"
  grep -q 'bq2419x_charger.o' "$K/drivers/power/Makefile" || \
    echo 'obj-$(CONFIG_BQ2419X_CHARGER) += bq2419x_charger.o' >> "$K/drivers/power/Makefile"
  if ! grep -q '^config BQ2419X_CHARGER' "$K/drivers/power/Kconfig"; then
    cat >> "$K/drivers/power/Kconfig" <<'KCFG'

config BQ2419X_CHARGER
    bool "Huawei BQ2419X charger for HWT101"
    depends on I2C
    default y
KCFG
  fi
  say "BQ2419X: IMPORTED exact Huawei K3V2 donor"
else
  say "BQ2419X: MISSING in reference tree"
fi

# 2) Search exact OEM symbol names in donor; copy only when a matching implementation exists.
for item in \
  'GOODIX:goodix_ts_probe:drivers/input/touchscreen' \
  'FT5X0X:ft5x0x_ts_probe:drivers/input/touchscreen' \
  'GC0339:gc0339_init:drivers/media/video/hik3/capture' \
  'S5K5CAG:s5k5cag_init:drivers/media/video/hik3/capture'
do
  IFS=: read -r name sym dst <<<"$item"
  f="$(find_symbol_file "$sym")"
  if [ -n "$f" ]; then
    rel="${f#$R/}"
    mkdir -p "$K/$(dirname "$rel")"
    cp -a "$f" "$K/$rel"
    say "$name: FOUND exact symbol source -> $rel"
  else
    say "$name: exact symbol source NOT FOUND in reference"
  fi
done

# 3) Base S10 already has S5K5CAG source. Record it even if donor search above missed it.
if [ -f "$K/drivers/media/video/hik3/capture/s5k5cag/s5k5cag.c" ]; then
  say "S5K5CAG_BASE: PRESENT in S10 tree"
fi

# 4) Inventory all plausible files for manual parity work.
say ""
say "Candidate hardware files in reference:"
find "$R/drivers" -type f \( \
  -iname '*goodix*' -o -iname '*gt9*' -o -iname '*ft5*' -o \
  -iname '*gc0339*' -o -iname '*s5k5*' -o -iname '*bq2419*' \) \
  2>/dev/null | sed "s#^$R/##" | sort | tee -a "$REPORT" || true
