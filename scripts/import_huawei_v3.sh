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
  # V3.8 FIX2:
  # The donor BQ2419X source references USB_EVENT_OTG_ID, but this donor tree
  # does not define it anywhere. The S10 OTG enum is:
  #   NONE, VBUS, ID, CHARGER, ENUMERATED
  # and V3.7 proved OTG_ID cannot alias USB_EVENT_ID because that creates
  # duplicate switch case values.
  #
  # Reconstruct the missing vendor extension as the next event value after
  # USB_EVENT_ENUMERATED. This preserves every existing S10 event value and
  # gives the BQ2419X OTG-only path a unique event code.
  if ! grep -R -q -w 'USB_EVENT_ENUMERATED' "$K/include/linux/usb" "$K/include/linux" 2>/dev/null; then
    say "ERROR: USB_EVENT_ENUMERATED missing from S10 USB API"
    exit 1
  fi

  if ! grep -q 'HWT101_USB_EVENT_OTG_ID_RECONSTRUCTED' "$K/drivers/power/bq2419x_charger.c"; then
    tmp="$K/drivers/power/.bq2419x_charger.c.hwt101"
    {
      echo '/* HWT101_USB_EVENT_OTG_ID_RECONSTRUCTED */'
      echo '#ifndef USB_EVENT_OTG_ID'
      echo '#define USB_EVENT_OTG_ID (USB_EVENT_ENUMERATED + 1)'
      echo '#endif'
      cat "$K/drivers/power/bq2419x_charger.c"
    } > "$tmp"
    mv "$tmp" "$K/drivers/power/bq2419x_charger.c"
  fi

  say "BQ2419X USB_EVENT_OTG_ID reconstructed as (USB_EVENT_ENUMERATED + 1)"
  say "Expected S10 numeric sequence: NONE=0 VBUS=1 ID=2 CHARGER=3 ENUMERATED=4 OTG_ID=5"

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


# HWT101_V3_10_LINK_PROVIDERS
# Import the exact Huawei source files that DEFINE the unresolved battery,
# thermal and HIUSB symbols from the current vmlinux link failure.
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
python3 "$SCRIPT_DIR/import_link_providers.py" "$K" "$R"
say "V3.10 exact battery/thermal/HIUSB link providers: IMPORTED"
