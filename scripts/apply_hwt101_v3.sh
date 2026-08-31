#!/usr/bin/env bash
set -euo pipefail
K="${1:-kernel}"
CFG="$K/.config"

echo "[V3] Install HWT101 SN65DSI83 reconstruction"
mkdir -p "$K/drivers/video/k3"
cp oem_recovered/display/sn65dsi83_hwt101.c "$K/drivers/video/k3/sn65dsi83_hwt101.c"
cp oem_recovered/display/sn65dsi83_oem_table.h "$K/drivers/video/k3/sn65dsi83_oem_table.h"
grep -q 'sn65dsi83_hwt101.o' "$K/drivers/video/k3/Makefile" || \
  echo 'obj-$(CONFIG_HWT101_SN65DSI83) += sn65dsi83_hwt101.o' >> "$K/drivers/video/k3/Makefile"
if ! grep -q '^config HWT101_SN65DSI83' "$K/drivers/video/Kconfig"; then
cat >> "$K/drivers/video/Kconfig" <<'KCFG'

config HWT101_SN65DSI83
    bool "HWT101 OEM SN65DSI83 bridge"
    depends on I2C && HAS_EARLYSUSPEND
    default y
KCFG
fi

# Preserve recovered camera blobs for later exact reconstruction.
mkdir -p "$K/hwt101-oem-recovered"
cp -a oem_recovered/camera "$K/hwt101-oem-recovered/"

set_cfg_y(){
  local name="$1"
  sed -i "/^# CONFIG_${name} is not set/d;/^CONFIG_${name}=/d" "$CFG"
  echo "CONFIG_${name}=y" >> "$CFG"
}
set_cfg_n(){
  local name="$1"
  sed -i "/^# CONFIG_${name} is not set/d;/^CONFIG_${name}=/d" "$CFG"
  echo "# CONFIG_${name} is not set" >> "$CFG"
}

for x in SWAP STAGING ZRAM XVMALLOC LZO_COMPRESS LZO_DECOMPRESS HWT101_SN65DSI83; do
  set_cfg_y "$x"
done
set_cfg_n ZRAM_DEBUG

# S10 already contains Huawei's native K3V2 S5K5CAG implementation and its
# capture Makefile wires it through CONFIG_HIK3_CAMERA_S5K5CAG.  Enable the
# native source instead of treating it as a missing external driver.
if [ -f "$K/drivers/media/video/hik3/capture/s5k5cag/s5k5cag.c" ]; then
  set_cfg_y VIDEO_HIK3_CAMERA
  set_cfg_y HIK3_CAMERA_S5K5CAG
fi

# Enable imported Huawei BQ2419X when present.
if [ -f "$K/drivers/power/bq2419x_charger.c" ]; then
  set_cfg_y BQ2419X_CHARGER
fi

# Keep module versioning setting from base, but never change it blindly.
# Exact OEM release.
# Old Linux 3.0.x appends '+' for a modified SCM tree when LOCALVERSION is
# unspecified, even with CONFIG_LOCALVERSION_AUTO disabled.
# Put the OEM suffix in CONFIG_LOCALVERSION and invoke make with LOCALVERSION=
# so the SCM '+' is suppressed deterministically.
sed -i '/^CONFIG_LOCALVERSION=/d;/^CONFIG_LOCALVERSION_AUTO=/d;/^# CONFIG_LOCALVERSION_AUTO is not set/d' "$CFG"
echo 'CONFIG_LOCALVERSION="-g883717a-dirty"' >> "$CFG"
echo '# CONFIG_LOCALVERSION_AUTO is not set' >> "$CFG"
rm -f "$K/.scmversion"

echo "[V3] Overlay applied"
