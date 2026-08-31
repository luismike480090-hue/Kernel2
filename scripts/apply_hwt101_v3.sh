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

# HWT101 V3.34 OEM filesystem parity.
# YAFFS lives below MISC_FILESYSTEMS in fs/Kconfig and YAFFS_FS depends on
# MTD_BLOCK. All parent/dependency symbols must therefore be forced on before
# oldnoconfig resolves the configuration.
for x in MISC_FILESYSTEMS MTD MTD_BLOCK YAFFS_FS YAFFS_YAFFS1 YAFFS_YAFFS2 YAFFS_AUTO_YAFFS2 YAFFS_XATTR; do
  set_cfg_y "$x"
done
set_cfg_n YAFFS_9BYTE_TAGS
set_cfg_n YAFFS_DOES_ECC
set_cfg_n YAFFS_DISABLE_TAGS_ECC
set_cfg_n YAFFS_ALWAYS_CHECK_CHUNK_ERASED
set_cfg_n YAFFS_EMPTY_LOST_AND_FOUND
set_cfg_n YAFFS_DISABLE_BLOCK_REFRESHING
set_cfg_n YAFFS_DISABLE_BACKGROUND

# Port the bundled older YAFFS VFS glue to this Linux 3.0.8 tree.
# 1) Big Kernel Lock header is obsolete and unused by this YAFFS copy.
# 2) file_system_type uses ->mount/mount_bdev instead of ->get_sb/get_sb_bdev.
# Only VFS registration glue is changed; NAND/MTD/YAFFS logic is untouched.
YAFFS_VFS="$K/fs/yaffs2/yaffs_vfs.c"
if [ -f "$YAFFS_VFS" ]; then
  sed -i '/^[[:space:]]*#include[[:space:]]*<linux\/smp_lock\.h>[[:space:]]*$/d' "$YAFFS_VFS"
  if grep -Eq '\b(lock_kernel|unlock_kernel)\b' "$YAFFS_VFS"; then
    echo "ERROR: YAFFS unexpectedly uses Big Kernel Lock calls after smp_lock.h removal"
    exit 97
  fi

  python3 - "$YAFFS_VFS" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text()
old1 = '''static int yaffs_read_super(struct file_system_type *fs,\n\t\t\t    int flags, const char *dev_name,\n\t\t\t    void *data, struct vfsmount *mnt)\n{\n\n\treturn get_sb_bdev(fs, flags, dev_name, data,\n\t\t\t   yaffs_internal_read_super_mtd, mnt);\n}\n'''
new1 = '''static struct dentry *yaffs_mount(struct file_system_type *fs,\n\t\t\t\t int flags, const char *dev_name, void *data)\n{\n\treturn mount_bdev(fs, flags, dev_name, data,\n\t\t\t  yaffs_internal_read_super_mtd);\n}\n'''
old2 = '''static int yaffs2_read_super(struct file_system_type *fs,\n\t\t\t     int flags, const char *dev_name, void *data,\n\t\t\t     struct vfsmount *mnt)\n{\n\treturn get_sb_bdev(fs, flags, dev_name, data,\n\t\t\t   yaffs2_internal_read_super_mtd, mnt);\n}\n'''
new2 = '''static struct dentry *yaffs2_mount(struct file_system_type *fs,\n\t\t\t\t  int flags, const char *dev_name, void *data)\n{\n\treturn mount_bdev(fs, flags, dev_name, data,\n\t\t\t  yaffs2_internal_read_super_mtd);\n}\n'''
for old, new, label in ((old1, new1, 'yaffs'), (old2, new2, 'yaffs2')):
    if old in s:
        s = s.replace(old, new, 1)
    elif new not in s:
        raise SystemExit('ERROR: expected legacy %s mount block not found' % label)
s = s.replace('\t.get_sb = yaffs_read_super,', '\t.mount = yaffs_mount,')
s = s.replace('\t.get_sb = yaffs2_read_super,', '\t.mount = yaffs2_mount,')
p.write_text(s)
PY

  grep -q 'mount_bdev(fs, flags, dev_name, data' "$YAFFS_VFS"
  grep -q '^[[:space:]]*\.mount = yaffs_mount,' "$YAFFS_VFS"
  grep -q '^[[:space:]]*\.mount = yaffs2_mount,' "$YAFFS_VFS"
  if grep -Eq '\b(get_sb_bdev|\.get_sb[[:space:]]*=)' "$YAFFS_VFS"; then
    echo "ERROR: legacy YAFFS get_sb VFS API still present"
    exit 98
  fi
fi

# HWT101 Wi-Fi parity: real unit uses external TI wl18xx/wlcore stack.
set_cfg_n BCMDHD
set_cfg_n BCMDHD_BCM
set_cfg_n BCMDHD_WEXT
set_cfg_n DHD_USE_SCHED_SCAN

# OEM kernel contains TPA2028 L/R, not a TFA9887 kernel driver.
set_cfg_n TFA9887

sed -i '/^CONFIG_LOCALVERSION=/d;/^CONFIG_LOCALVERSION_AUTO=/d;/^# CONFIG_LOCALVERSION_AUTO is not set/d' "$CFG"
echo 'CONFIG_LOCALVERSION="-g883717a-dirty"' >> "$CFG"
echo '# CONFIG_LOCALVERSION_AUTO is not set' >> "$CFG"
rm -f "$K/.scmversion"

echo "[V3.34 FINAL] Overlay applied: display + Goodix + cameras + charger + TI WiLink + OEM YAFFS2 Linux-3.0 VFS compatibility; Broadcom DHD removed"
