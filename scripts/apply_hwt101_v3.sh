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

if [ -f "$K/drivers/media/video/hik3/capture/s5k5cag/s5k5cag.c" ]; then
  set_cfg_y VIDEO_HIK3_CAMERA
  set_cfg_y HIK3_CAMERA_S5K5CAG
fi

if [ -f "$K/drivers/power/bq2419x_charger.c" ]; then
  set_cfg_y BQ2419X_CHARGER
fi

# FINAL HWT101 connectivity parity.
# Runtime evidence from the real tablet identifies Goodix touch and TI WiLink.
if [ -d "huawei-k3-reference/drivers/misc/ti-st" ]; then
  python3 scripts/enable_ti_wilink_final.py "$K" huawei-k3-reference
  cat HWT101-FINAL-TI-WILINK.txt
else
  echo "ERROR: Huawei K3V2 donor missing; cannot install exact TI WiLink transport"
  exit 96
fi

# HWT101 V3.31 OEM filesystem parity.
# The stock HWT101 kallsyms contains init_yaffs_fs, yaffs2_mount and the full
# YAFFS MTD glue. /system, /cache and /cust are NAND MTD partitions, therefore
# YAFFS2 must be built into the kernel (not a module) so Android can mount them.
for x in MTD MTD_BLOCK YAFFS_FS YAFFS_YAFFS1 YAFFS_YAFFS2 YAFFS_AUTO_YAFFS2 YAFFS_XATTR; do
  set_cfg_y "$x"
done
set_cfg_n YAFFS_9BYTE_TAGS
set_cfg_n YAFFS_DOES_ECC
set_cfg_n YAFFS_DISABLE_TAGS_ECC
set_cfg_n YAFFS_ALWAYS_CHECK_CHUNK_ERASED
set_cfg_n YAFFS_EMPTY_LOST_AND_FOUND
set_cfg_n YAFFS_DISABLE_BLOCK_REFRESHING
set_cfg_n YAFFS_DISABLE_BACKGROUND

# HWT101 V3.31 Wi-Fi parity.
# The real HWT101 uses external TI wl18xx/wlcore/wlcore_sdio modules. Its OEM
# kallsyms has no Broadcom DHD symbols. The S10 donor enables Broadcom by
# default, so explicitly remove both donor DHD variants to avoid SDIO probing
# and power-control conflicts with the TI WiLink device.
set_cfg_n BCMDHD
set_cfg_n BCMDHD_BCM
set_cfg_n BCMDHD_WEXT
set_cfg_n DHD_USE_SCHED_SCAN

# TFA9887 is intentionally not enabled: stock HWT101 kallsyms contains no
# tfa9887 driver, while it does contain the TPA2028 left/right amplifier.
set_cfg_n TFA9887

sed -i '/^CONFIG_LOCALVERSION=/d;/^CONFIG_LOCALVERSION_AUTO=/d;/^# CONFIG_LOCALVERSION_AUTO is not set/d' "$CFG"
echo 'CONFIG_LOCALVERSION="-g883717a-dirty"' >> "$CFG"
echo '# CONFIG_LOCALVERSION_AUTO is not set' >> "$CFG"
rm -f "$K/.scmversion"

echo "[V3.31 FINAL] Overlay applied: display + Goodix + cameras + charger + TI WiLink + OEM YAFFS2; Broadcom DHD removed"
