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

  # Import ALL linux/power headers from the same Huawei K3V2 donor.
  # The BQ2419X source depends not only on bq2419x_charger.h but also
  # on bq27510_battery.h (and potentially companion power headers).
  # Copying the donor power-header set avoids one-header-at-a-time failures.
  mkdir -p "$K/include/linux/power"
  if [ -d "$R/include/linux/power" ]; then
    cp -a "$R/include/linux/power/." "$K/include/linux/power/"
    say "Huawei power headers: IMPORTED all include/linux/power/*"
  else
    say "Huawei power headers: donor include/linux/power is MISSING"
    exit 1
  fi

  for req in bq2419x_charger.h bq27510_battery.h; do
    if [ ! -s "$K/include/linux/power/$req" ]; then
      say "Required Huawei power header MISSING: $req"
      exit 1
    fi
  done

  # Keep the S10 USB header set intact.
  # V3.6 replacing include/linux/usb/* broke FSA880, so never replace it.
  #
  # V3.7 mapped USB_EVENT_OTG_ID to USB_EVENT_ID, but the new build proved
  # that this creates duplicate switch case values. Therefore those are NOT
  # equivalent events in this driver.
  #
  # Import ONLY the exact donor definition of USB_EVENT_OTG_ID. We extract
  # its enum/define value from the Huawei donor and inject that single
  # definition before compiling bq2419x_charger.c.
  OTG_LINE="$(grep -R -h -E '^[[:space:]]*(#define[[:space:]]+USB_EVENT_OTG_ID|USB_EVENT_OTG_ID[[:space:]]*=)' \
      "$R/include" "$R/arch/arm/mach-k3v2/include" 2>/dev/null | head -n1 || true)"

  if [ -z "$OTG_LINE" ]; then
    say "ERROR: exact USB_EVENT_OTG_ID definition not found in Huawei donor"
    exit 1
  fi

  say "Huawei donor USB_EVENT_OTG_ID definition: $OTG_LINE"

  OTG_VALUE="$(printf '%s\n' "$OTG_LINE" | sed -n \
      -e 's/^[[:space:]]*#define[[:space:]]\+USB_EVENT_OTG_ID[[:space:]]\+\([^[:space:]\/,}]*\).*/\1/p' \
      -e 's/^[[:space:]]*USB_EVENT_OTG_ID[[:space:]]*=[[:space:]]*\([^[:space:],}]*\).*/\1/p' | head -n1)"

  if [ -z "$OTG_VALUE" ]; then
    say "ERROR: could not parse donor USB_EVENT_OTG_ID value"
    exit 1
  fi

  # Reject the known-wrong alias that caused V3.7 duplicate case values.
  if [ "$OTG_VALUE" = "USB_EVENT_ID" ]; then
    say "ERROR: donor parse unexpectedly aliases USB_EVENT_OTG_ID to USB_EVENT_ID"
    exit 1
  fi

  if ! grep -q 'HWT101_USB_EVENT_OTG_ID_EXACT' "$K/drivers/power/bq2419x_charger.c"; then
    tmp="$K/drivers/power/.bq2419x_charger.c.hwt101"
    {
      echo '/* HWT101_USB_EVENT_OTG_ID_EXACT */'
      echo '#ifndef USB_EVENT_OTG_ID'
      printf '#define USB_EVENT_OTG_ID %s\n' "$OTG_VALUE"
      echo '#endif'
      cat "$K/drivers/power/bq2419x_charger.c"
    } > "$tmp"
    mv "$tmp" "$K/drivers/power/bq2419x_charger.c"
  fi
  say "BQ2419X exact donor USB_EVENT_OTG_ID=$OTG_VALUE: APPLIED"

  # Prove the S10 FSA880 event API was NOT destroyed.
  if ! grep -R -q -w 'USB_CONNECT' "$K/include" 2>/dev/null; then
    say "ERROR: USB_CONNECT missing from base headers"
    exit 1
  fi
  if ! grep -R -q -w 'USB_DISCONNECT' "$K/include" 2>/dev/null; then
    say "ERROR: USB_DISCONNECT missing from base headers"
    exit 1
  fi
  say "S10 USB_CONNECT / USB_DISCONNECT API: PRESERVED"

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
  say "BQ2419X include dependencies:"
  grep '^#include' "$K/drivers/power/bq2419x_charger.c" | tee -a "$REPORT" || true
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
