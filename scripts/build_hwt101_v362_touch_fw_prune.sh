#!/usr/bin/env bash
set -euo pipefail

ROOT="$PWD"
OEM_SIZE=4124692
V361_SIZE=4239556
SRC_SHA=08fd9448a6bfc6923a5caa9da8260d3be930686c

rm -rf kernel gcc46

git clone --depth 1 -b cm-10.1 https://github.com/mangusta86/android_kernel_huawei_k3v2oem1.git kernel
test "$(git -C kernel rev-parse HEAD)" = "$SRC_SHA"
git -C kernel rev-parse HEAD | tee V362-SOURCE-SHA.txt

git clone --depth 1 https://github.com/radxa/android-platform-prebuilts-gcc-linux-x86-arm-arm-eabi-4.6.git gcc46
TC="$ROOT/gcc46/bin/arm-eabi-"
"${TC}gcc" --version | tee V362-GCC.txt
grep -qi '4.6.x-google 20120106' V362-GCC.txt

sed -i -E 's/defined[[:space:]]*\([[:space:]]*\@([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*\)/@\1/g' kernel/kernel/timeconst.pl || true
sed -i -E 's/defined[[:space:]]*\([[:space:]]*\%([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*\)/%\1/g' kernel/kernel/timeconst.pl || true

export ARCH=arm SUBARCH=arm CROSS_COMPILE="$TC"

pushd kernel >/dev/null
make mrproper
make hisi_k3v2oem1_defconfig
set_y(){ sed -i "/^# CONFIG_$1 is not set/d;/^CONFIG_$1=/d" .config; echo "CONFIG_$1=y" >> .config; }
set_n(){ sed -i "/^# CONFIG_$1 is not set/d;/^CONFIG_$1=/d" .config; echo "# CONFIG_$1 is not set" >> .config; }
set_v(){ sed -i "/^# CONFIG_$1 is not set/d;/^CONFIG_$1=/d" .config; echo "CONFIG_$1=$2" >> .config; }

set_y LCD_TOSHIBA_MDW70
for x in LCD_PANASONIC_VVX10F002A00 LCD_CMI_OTM1280A LCD_SAMSUNG_LMS350DF04 LCD_SAMSUNG_S6E39A LCD_SHARP_LS035B3SX LCD_CMI_PT045TN07 LCD_JDI_OTM1282B LCD_TOSHIBA_MDY90 LCD_K3_FAKE; do set_n "$x"; done
for x in FB_K3 FB_K3_CLCD I2C REGULATOR HAS_EARLYSUSPEND EARLYSUSPEND LEDS_K3_6421 ANDROID_K3_VIBRATOR ARM_HISIK3_WATCHDOG; do set_y "$x"; done

for x in MTD MTD_CHAR MTD_BLOCK MTD_PARTITIONS MTD_CMDLINE_PARTS MTD_NAND MTD_NAND_IDS MISC_FILESYSTEMS YAFFS_FS YAFFS_YAFFS2; do set_y "$x"; done
for x in SWAP ZRAM XVMALLOC ZRAM_DEBUG; do set_n "$x"; done

for x in SRECORDER BALONG_POWER BALONG_RMNET MHL_SII8240 MHL_SII9244 K3_LOG BCMDHD_BCM DHD_USE_SCHED_SCAN; do set_n "$x"; done
for x in TOUCH_INPUT_SYNAPTICS_RMI4 TOUCHSCREEN_RMI4_SYNAPTICS_GENERIC SYNAPTICS_TOUCH_KEY RMI4_BUS RMI4_DEBUG RMI4_FWLIB RMI4_I2C RMI4_SPI RMI4_GENERIC RMI4_F1A RMI4_F09 RMI4_F11 RMI4_F11_PEN RMI4_VIRTUAL_BUTTON RMI4_F17 RMI4_F19 RMI4_F21 RMI4_F34 RMI4_F54 RMI4_DEV; do set_n "$x"; done
for x in CYPRESS_CYTTSP4_BUS TOUCHSCREEN_CYPRESS_CYTTSP4 TOUCHSCREEN_CYPRESS_CYTTSP4_I2C TOUCHSCREEN_CYPRESS_CYTTSP4_SPI TOUCHSCREEN_MXT224E; do set_n "$x"; done
for x in MODEM_BOOT MODEM_BOOT_QSC6085 MODEM_BOOT_MTK6252 MODEM_BOOT_SPRD8803G XMM_POWER XMM_RMNET AUDIENCE USB_NET_SMSC95XX; do set_n "$x"; done
for x in HUAWEI_FEATURE_SENSORS_ACC_GYRO_LSM330 HUAWEI_FEATURE_SENSORS_AKM8963 HUAWEI_FEATURE_PROXIMITY_APDS990X; do set_n "$x"; done
for x in HIK3_CAMERA_OV8830 HIK3_CAMERA_SONYIMX105 HIK3_CAMERA_S5K3H2YX_FOXCONN HIK3_CAMERA_S5K3H2YX_SAMSUNGEM HIK3_CAMERA_MT9M114 HIK3_CAMERA_SONYIMX091; do set_n "$x"; done
set_y HIK3_CAMERA_S5K5CAG

set_v PANIC_TIMEOUT 0
sed -i '/^CONFIG_LOCALVERSION=/d;/^CONFIG_LOCALVERSION_AUTO=/d;/^# CONFIG_LOCALVERSION_AUTO is not set/d' .config
echo 'CONFIG_LOCALVERSION="-g883717a-dirty"' >> .config
echo '# CONFIG_LOCALVERSION_AUTO is not set' >> .config
rm -f .scmversion
make oldnoconfig
popd >/dev/null

python3 scripts/reconstruct_t101_board_cm10.py kernel | tee V362-BOARD-PATCH.txt
grep -q 'platform=21, i2c=1/10/2' V362-BOARD-PATCH.txt
cp oem_recovered/display/sn65dsi83_hwt101.c kernel/drivers/video/k3/sn65dsi83_hwt101.c
cp oem_recovered/display/sn65dsi83_oem_table.h kernel/drivers/video/k3/sn65dsi83_oem_table.h
python3 scripts/patch_hwt101_v350_golden.py kernel | tee V362-GOLDEN-PATCH.txt
python3 scripts/patch_hwt101_yaffs_v350.py kernel | tee V362-YAFFS-PATCH.txt
python3 scripts/patch_hwt101_v356_panel_parity.py kernel | tee V362-PANEL-PATCH.txt

# V3.61 parity: remove panel objects that the donor Makefile links unconditionally.
python3 - <<'PY' | tee V362-PANEL-PRUNE.txt
from pathlib import Path
p=Path('kernel/drivers/video/k3/Makefile')
s=p.read_text()
donors=[
    'panel/ldi_samsung_LMS350DF04.o',
    'panel/mipi_sharp_LS035B3SX.o',
    'panel/mipi_samsung_S6E39A.o',
    'panel/mipi_panasonic_VVX10F002A00.o',
    'panel/mipi_cmi_OTM1280A.o',
    'panel/mipi_jdi_OTM1282B.o',
    'panel/mipi_cmi_PT045TN07.o',
    'panel/mipi_toshiba_MDY90.o',
]
lines=s.splitlines()
removed=[]
out=[]
for line in lines:
    hit=next((d for d in donors if d in line), None)
    if hit:
        removed.append(hit)
        continue
    out.append(line)
target='\tpanel/mipi_toshiba_MDW70_V001.o \\'
if target not in out:
    raise SystemExit('Toshiba MDW70 Makefile line missing')
out[out.index(target)]='\tpanel/mipi_toshiba_MDW70_V001.o'
s='\n'.join(out)+'\n'
if any(d in s for d in donors):
    raise SystemExit('donor panel object survived')
if 'panel/mipi_toshiba_MDW70_V001.o' not in s:
    raise SystemExit('Toshiba MDW70 object lost')
if len(removed) != 7:
    raise SystemExit('unexpected donor panel removal count: %d %r' % (len(removed), removed))
p.write_text(s)
print('V362_PANEL_OBJECT_PRUNE=PASS')
print('REMOVED_COUNT=%d' % len(removed))
for x in removed: print('REMOVED='+x)
print('KEPT=panel/mipi_toshiba_MDW70_V001.o')
PY

# V3.62: stop embedding only donor touch firmware. IPPS firmware is intentionally preserved.
python3 - <<'PY' | tee V362-TOUCH-FW-PRUNE.txt
from pathlib import Path
p=Path('kernel/firmware/Makefile')
lines=p.read_text().splitlines()
out=[]
removed=[]
i=0
while i < len(lines):
    line=lines[i]
    if line.startswith('fw-shipped-$(CONFIG_TOUCHSCREEN_RMI4_SYNAPTICS_GENERIC) +='):
        while True:
            removed.append(lines[i])
            cont=lines[i].rstrip().endswith('\\')
            i += 1
            if not cont or i >= len(lines):
                break
        continue
    if line.strip() == 'fw-shipped-y += cyttsp4_fw.bin':
        removed.append(line)
        i += 1
        continue
    out.append(line)
    i += 1
s='\n'.join(out)+'\n'
if 'rmi4/TM2429-001.img' in s:
    raise SystemExit('RMI4 firmware stanza survived')
if 'fw-shipped-y += cyttsp4_fw.bin' in s:
    raise SystemExit('Cypress firmware stanza survived')
if 'fw-shipped-$(CONFIG_IPPS_SUPPORT) += ipps/ipps-v2.bin ipps/ipps-v2-es.bin' not in s:
    raise SystemExit('IPPS firmware rule was lost')
p.write_text(s)
print('V362_TOUCH_FW_PRUNE=PASS')
print('REMOVED_LINES=%d' % len(removed))
for x in removed: print('REMOVED='+x)
print('PRESERVED=ipps/ipps-v2.bin')
print('PRESERVED=ipps/ipps-v2-es.bin')
PY

# Reassert touch donor config OFF after every reconstruction patch, then normalize once more.
pushd kernel >/dev/null
set_n(){ sed -i "/^# CONFIG_$1 is not set/d;/^CONFIG_$1=/d" .config; echo "# CONFIG_$1 is not set" >> .config; }
for x in TOUCH_INPUT_SYNAPTICS_RMI4 TOUCHSCREEN_RMI4_SYNAPTICS_GENERIC SYNAPTICS_TOUCH_KEY RMI4_BUS RMI4_DEBUG RMI4_FWLIB RMI4_I2C RMI4_SPI RMI4_GENERIC RMI4_F1A RMI4_F09 RMI4_F11 RMI4_F11_PEN RMI4_VIRTUAL_BUTTON RMI4_F17 RMI4_F19 RMI4_F21 RMI4_F34 RMI4_F54 RMI4_DEV CYPRESS_CYTTSP4_BUS TOUCHSCREEN_CYPRESS_CYTTSP4 TOUCHSCREEN_CYPRESS_CYTTSP4_I2C TOUCHSCREEN_CYPRESS_CYTTSP4_SPI TOUCHSCREEN_MXT224E; do set_n "$x"; done
make oldnoconfig
popd >/dev/null

cp kernel/.config V362-CONFIG.txt
cp kernel/drivers/video/k3/Makefile V362-K3-MAKEFILE.txt
cp kernel/firmware/Makefile V362-FIRMWARE-MAKEFILE.txt

# Source hard gate.
P=kernel/drivers/video/k3/panel/mipi_toshiba_MDW70_V001.c
MK=kernel/drivers/video/k3/Makefile
FW=kernel/firmware/Makefile
grep -q 'pinfo->xres = 1280;' "$P"
grep -q 'pinfo->yres = 800;' "$P"
grep -q 'pinfo->orientation = LCD_LANDSCAPE;' "$P"
grep -q 'HWT356 PANEL_PARITY 1280x800 LANDSCAPE' "$P"
grep -q 'obj-y := sn65dsi83_hwt101.o' "$MK"
grep -q 'panel/mipi_toshiba_MDW70_V001.o' "$MK"
for bad in ldi_samsung_LMS350DF04 mipi_sharp_LS035B3SX mipi_samsung_S6E39A mipi_panasonic_VVX10F002A00 mipi_cmi_OTM1280A mipi_jdi_OTM1282B mipi_cmi_PT045TN07 mipi_toshiba_MDY90; do
  ! grep -q "panel/${bad}.o" "$MK" || { echo "BAD_PANEL_OBJECT_SURVIVED=$bad"; exit 80; }
done
for x in TOUCH_INPUT_SYNAPTICS_RMI4 TOUCHSCREEN_RMI4_SYNAPTICS_GENERIC RMI4_BUS RMI4_FWLIB RMI4_I2C RMI4_SPI RMI4_GENERIC CYPRESS_CYTTSP4_BUS TOUCHSCREEN_CYPRESS_CYTTSP4 TOUCHSCREEN_CYPRESS_CYTTSP4_I2C TOUCHSCREEN_CYPRESS_CYTTSP4_SPI MODEM_BOOT MODEM_BOOT_QSC6085 MODEM_BOOT_MTK6252 MODEM_BOOT_SPRD8803G XMM_POWER XMM_RMNET AUDIENCE USB_NET_SMSC95XX; do
  ! grep -q "^CONFIG_${x}=y" kernel/.config || { echo "BAD_CONFIG_SURVIVED=$x"; exit 81; }
done
! grep -q 'rmi4/TM2429-001.img' "$FW"
! grep -q '^fw-shipped-y += cyttsp4_fw.bin$' "$FW"
grep -q 'fw-shipped-$(CONFIG_IPPS_SUPPORT) += ipps/ipps-v2.bin ipps/ipps-v2-es.bin' "$FW"
grep -qx 'CONFIG_HIK3_CAMERA_S5K5CAG=y' kernel/.config
grep -qx '# CONFIG_SWAP is not set' kernel/.config
grep -qx '# CONFIG_ZRAM is not set' kernel/.config
! grep -Rqs 'hwt355_screen_checkpoint\|HWT355CHK' kernel
echo V362_TOUCH_FW_SOURCE_GATE=PASS | tee V362-GATE.txt

# Build.
pushd kernel >/dev/null
make -j2 zImage 2>&1 | tee ../V362-BUILD.log
cp arch/arm/boot/zImage ../HWT101-V3.62-FIX10-TOUCH-FW-PRUNE-zImage
cp vmlinux ../HWT101-V3.62-TOUCH-FW-PRUNE-vmlinux
cp System.map ../HWT101-V3.62-TOUCH-FW-PRUNE-System.map
"$TC"nm -n vmlinux > ../V362-NM-ORDERED.txt
sha256sum arch/arm/boot/zImage | tee ../V362-SHA256.txt
stat -c%s arch/arm/boot/zImage | tee ../V362-SIZE.txt
popd >/dev/null

MAP=kernel/System.map
VM=kernel/vmlinux
Z=kernel/arch/arm/boot/zImage
SIZE=$(stat -c%s "$Z")
{
  echo '=== V3.62 HWT101 TOUCH FIRMWARE PRUNE AUDIT ==='
  for sym in k3_fb_init mipi_toshiba_panel_init mipi_toshiba_panel_set_fastboot sn65dsi83_probe mipi_dsi_probe ldi_probe nand_scan hinand_probe s5k5cag_module_init; do
    grep -Eq " [tT] ${sym}$" "$MAP" || { echo "MISSING_SYMBOL=$sym"; exit 91; }
    echo "OK_SYMBOL=$sym"
  done
  grep -aFq 'HWT356 PANEL_PARITY 1280x800 LANDSCAPE' "$VM" || { echo MISSING_PANEL_MARKER; exit 92; }
  if grep -Eq '(MK_FW|IHEX|AS) +firmware/rmi4/TM2429-001\.img' V362-BUILD.log; then echo RMI4_FW_STILL_EMBEDDED; exit 93; fi
  if grep -Eq '(MK_FW|IHEX|AS) +firmware/cyttsp4_fw\.bin' V362-BUILD.log; then echo CYPRESS_FW_STILL_EMBEDDED; exit 94; fi
  grep -Eq '(MK_FW|IHEX|AS) +firmware/ipps/ipps-v2\.bin' V362-BUILD.log || { echo IPPS_V2_NOT_EMBEDDED; exit 95; }
  grep -Eq '(MK_FW|IHEX|AS) +firmware/ipps/ipps-v2-es\.bin' V362-BUILD.log || { echo IPPS_V2_ES_NOT_EMBEDDED; exit 96; }
  echo TOUCH_DONOR_FIRMWARE=REMOVED
  echo IPPS_FIRMWARE=PRESERVED
  echo TOSHIBA_MDW70=BUILTIN
  echo S5K5CAG=BUILTIN
  echo ZIMAGE_SIZE=$SIZE
  echo V361_ZIMAGE_SIZE=$V361_SIZE
  echo SAVED_VS_V361=$((V361_SIZE-SIZE))
  echo OEM_ZIMAGE_SIZE=$OEM_SIZE
  echo DELTA_VS_OEM=$((SIZE-OEM_SIZE))
  if [ "$SIZE" -le "$OEM_SIZE" ]; then echo SIZE_VS_OEM=PASS; else echo SIZE_VS_OEM=FAIL; exit 97; fi
  echo PANEL=1280x800_LANDSCAPE
  echo SWAP=OFF
  echo ZRAM=OFF
  echo V362_BINARY=PASS
} | tee V362-FINAL-AUDIT.txt
