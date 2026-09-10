#!/usr/bin/env python3
from pathlib import Path

src = Path('scripts/build_hwt101_v362_touch_fw_prune.sh')
dst = Path('scripts/build_hwt101_v364_mem_nand_diag.sh')
s = src.read_text()

# Promote names from V3.62 to V3.64 while preserving the same exact donor/toolchain.
s = s.replace('V3.62', 'V3.64').replace('V362', 'V364')
s = s.replace('TOUCH-FW-PRUNE', 'MEM-NAND-DIAG')
s = s.replace('TOUCH FIRMWARE PRUNE AUDIT', 'MEMORY + NAND DIAG AUDIT')

# Compare the result against the physically tested V3.63 kernel.
s = s.replace('V361_SIZE=4239556', 'V363_SIZE=4025164')
s = s.replace('V361_ZIMAGE_SIZE=$V361_SIZE', 'V363_ZIMAGE_SIZE=$V363_SIZE')
s = s.replace('SAVED_VS_V361=$((V361_SIZE-SIZE))', 'DELTA_VS_V363=$((SIZE-V363_SIZE))')

# Reproduce the V3.62B forced-firmware fix and V3.63 NTFS cut.
marker = 'set_v PANIC_TIMEOUT 0\n'
insert = marker + '''set_y FIRMWARE_IN_KERNEL\nset_v EXTRA_FIRMWARE '\"\"'\nfor x in NTFS_FS NTFS_DEBUG NTFS_RW; do set_n "$x"; done\n'''
if marker not in s:
    raise SystemExit('initial config marker missing')
s = s.replace(marker, insert, 1)

touch_line = 'for x in TOUCH_INPUT_SYNAPTICS_RMI4 TOUCHSCREEN_RMI4_SYNAPTICS_GENERIC SYNAPTICS_TOUCH_KEY RMI4_BUS RMI4_DEBUG RMI4_FWLIB RMI4_I2C RMI4_SPI RMI4_GENERIC RMI4_F1A RMI4_F09 RMI4_F11 RMI4_F11_PEN RMI4_VIRTUAL_BUTTON RMI4_F17 RMI4_F19 RMI4_F21 RMI4_F34 RMI4_F54 RMI4_DEV CYPRESS_CYTTSP4_BUS TOUCHSCREEN_CYPRESS_CYTTSP4 TOUCHSCREEN_CYPRESS_CYTTSP4_I2C TOUCHSCREEN_CYPRESS_CYTTSP4_SPI TOUCHSCREEN_MXT224E; do set_n "$x"; done\n'
second = touch_line + '''set_y(){ sed -i "/^# CONFIG_$1 is not set/d;/^CONFIG_$1=/d" .config; echo "CONFIG_$1=y" >> .config; }\nset_v(){ sed -i "/^# CONFIG_$1 is not set/d;/^CONFIG_$1=/d" .config; echo "CONFIG_$1=$2" >> .config; }\nset_y FIRMWARE_IN_KERNEL\nset_v EXTRA_FIRMWARE '\"\"'\nfor x in NTFS_FS NTFS_DEBUG NTFS_RW; do set_n "$x"; done\n'''
if touch_line not in s:
    raise SystemExit('post-patch config marker missing')
s = s.replace(touch_line, second, 1)

# Apply V3.64 after all reconstructed OEM components are installed, before build.
panel = 'python3 scripts/patch_hwt101_v356_panel_parity.py kernel | tee V364-PANEL-PATCH.txt\n'
if panel not in s:
    raise SystemExit('panel patch marker missing')
s = s.replace(panel, panel + 'python3 scripts/patch_hwt101_v364_mem_nand_diag.py kernel | tee V364-MEM-NAND-PATCH.txt\n', 1)

# Storage/filesystem hard gates retained from V3.63, plus exact memory/NAND diag source gates.
gate = "grep -qx 'CONFIG_HIK3_CAMERA_S5K5CAG=y' kernel/.config\n"
extra = '''grep -qx 'CONFIG_EXTRA_FIRMWARE=""' kernel/.config\ngrep -qx 'CONFIG_FIRMWARE_IN_KERNEL=y' kernel/.config\ngrep -qx '# CONFIG_NTFS_FS is not set' kernel/.config\ngrep -qx 'CONFIG_FAT_FS=y' kernel/.config\ngrep -qx 'CONFIG_VFAT_FS=y' kernel/.config\ngrep -qx 'CONFIG_YAFFS_FS=y' kernel/.config\ngrep -qx 'CONFIG_YAFFS_YAFFS2=y' kernel/.config\ngrep -qx 'CONFIG_MMC=y' kernel/.config\ngrep -qx 'CONFIG_IPPS_SUPPORT=y' kernel/.config\ngrep -q '#define LCD_XRES.*(1280)' kernel/arch/arm/mach-k3v2/include/mach/hisi_mem.h\ngrep -q '#define LCD_YRES.*(800)' kernel/arch/arm/mach-k3v2/include/mach/hisi_mem.h\ngrep -q 'HISI_MEM_GPU_SIZE.*160497664UL' kernel/arch/arm/mach-k3v2/include/mach/hisi_mem.h\ngrep -q 'HISI_MEM_CODEC_SIZE.*28311552UL' kernel/arch/arm/mach-k3v2/include/mach/hisi_mem.h\ngrep -q 'HISI_PMEM_GRALLOC_SIZE.*58720256UL' kernel/arch/arm/mach-k3v2/include/mach/hisi_mem.h\ngrep -q 'HISI_PMEM_OVERLAY_SIZE.*67108864UL' kernel/arch/arm/mach-k3v2/include/mach/hisi_mem.h\ngrep -q 'HISI_MEM_VPP_SIZE.*0UL' kernel/arch/arm/mach-k3v2/include/mach/hisi_mem.h\ngrep -q 'HISI_MEM_FB_SIZE.*0UL' kernel/arch/arm/mach-k3v2/include/mach/hisi_mem.h\ngrep -q 'create_proc_read_entry("hwt_hinand_diag",0444' kernel/drivers/mtd/nand/hinand_hwt101.c\n'''
if gate not in s:
    raise SystemExit('source gate marker missing')
s = s.replace(gate, extra + gate, 1)

# Ensure NTFS is still absent and the diagnostic symbol/node are linked.
audit_marker = "grep -aFq 'HWT356 PANEL_PARITY 1280x800 LANDSCAPE' \"$VM\" || { echo MISSING_PANEL_MARKER; exit 92; }\n"
if audit_marker not in s:
    raise SystemExit('binary audit marker missing')
s = s.replace(audit_marker, audit_marker + '''  if grep -Eq 'CC +fs/ntfs/' V364-BUILD.log; then echo NTFS_OBJECT_STILL_COMPILED; exit 98; fi\n  grep -Eq ' [tT] hwt_hinand_diag_read$' "$MAP" || { echo MISSING_HINAND_DIAG_SYMBOL; exit 99; }\n''', 1)

status_marker = '  echo TOUCH_DONOR_FIRMWARE=REMOVED\n'
if status_marker not in s:
    raise SystemExit('status marker missing')
s = s.replace(status_marker, status_marker + '''  echo NTFS=OFF\n  echo OEM_MEMORY_PARITY=ENABLED\n  echo HINAND_PROC_DIAG=/proc/hwt_hinand_diag\n''', 1)

dst.write_text(s)
print('V364_DERIVATION=PASS')
print('BASELINE_V363_SIZE=4025164')
print('NEW_CHANGE_1=OEM_MEMORY_PARITY')
print('NEW_CHANGE_2=READONLY_HINAND_PROC_DIAGNOSTIC')
