#!/usr/bin/env bash
set -euo pipefail
K="${1:-kernel}"

echo "[1] Installing recovered HWT101 SN65DSI83 source..."
mkdir -p "$K/drivers/video/k3"
cp oem_recovered/display/sn65dsi83_hwt101.c "$K/drivers/video/k3/sn65dsi83_hwt101.c"
cp oem_recovered/display/sn65dsi83_oem_table.h "$K/drivers/video/k3/sn65dsi83_oem_table.h"
grep -q 'sn65dsi83_hwt101.o' "$K/drivers/video/k3/Makefile" || \
    echo 'obj-$(CONFIG_HWT101_SN65DSI83) += sn65dsi83_hwt101.o' >> "$K/drivers/video/k3/Makefile"

if ! grep -q 'config HWT101_SN65DSI83' "$K/drivers/video/Kconfig"; then
cat >> "$K/drivers/video/Kconfig" <<'EOF'

config HWT101_SN65DSI83
    bool "HWT101 OEM SN65DSI83 bridge"
    depends on I2C && HAS_EARLYSUSPEND
    default y
EOF
fi

echo "[2] Keep exact OEM camera blobs in recovery workspace."
mkdir -p "$K/hwt101-oem-recovered"
cp -a oem_recovered/camera "$K/hwt101-oem-recovered/"

echo "[3] Enable SWAP/ZRAM only; preserve remaining selected config."
CFG="$K/.config"
grep -q '^CONFIG_SWAP=y' "$CFG" || { sed -i '/^# CONFIG_SWAP is not set/c\CONFIG_SWAP=y' "$CFG"; grep -q '^CONFIG_SWAP=y' "$CFG" || echo CONFIG_SWAP=y >> "$CFG"; }
for x in STAGING ZRAM XVMALLOC LZO_COMPRESS LZO_DECOMPRESS HWT101_SN65DSI83; do
    grep -q "^CONFIG_${x}=y" "$CFG" || echo "CONFIG_${x}=y" >> "$CFG"
done
sed -i '/^CONFIG_ZRAM_DEBUG=/d;/^# CONFIG_ZRAM_DEBUG is not set/d' "$CFG"
echo '# CONFIG_ZRAM_DEBUG is not set' >> "$CFG"

echo "[4] Force OEM kernel release suffix."
sed -i '/^CONFIG_LOCALVERSION=/d;/^CONFIG_LOCALVERSION_AUTO=/d' "$CFG"
echo 'CONFIG_LOCALVERSION="-g883717a-dirty"' >> "$CFG"
echo '# CONFIG_LOCALVERSION_AUTO is not set' >> "$CFG"

echo "Overlay installed."
