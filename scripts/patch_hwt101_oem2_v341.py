#!/usr/bin/env python3
from pathlib import Path
import re, sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch_hwt101_oem2_v341.py <kernel-root>')
K = Path(sys.argv[1])
board = K/'arch/arm/mach-k3v2/board-k3v2oem2.c'
if not board.exists():
    raise SystemExit('board-k3v2oem2.c not found')
s = board.read_text()

# OEM live kernel exposes __mach_desc_K3V2OEM2 while machine name remains k3v2oem1.
if 'MACHINE_START(K3V2OEM2, "k3v2oem1")' not in s:
    raise SystemExit('unexpected OEM2 machine descriptor')

# SN65 bridge uses LDO17 lcd-vcc on the HWT101 board.
reg = K/'arch/arm/mach-k3v2/include/mach/board-hi6421-regulator.h'
rs = reg.read_text()
needle = 'static struct regulator_consumer_supply ldo17_consumers[] = {\n\tREGULATOR_SUPPLY("lcdanalog-vcc", "k3_dev_lcd"),\n};'
replacement = 'static struct regulator_consumer_supply ldo17_consumers[] = {\n\tREGULATOR_SUPPLY("lcdanalog-vcc", "k3_dev_lcd"),\n\tREGULATOR_SUPPLY("lcd-vcc", "sn65dsi83"),\n};'
if needle in rs:
    rs = rs.replace(needle, replacement)
elif 'REGULATOR_SUPPLY("lcd-vcc", "sn65dsi83")' not in rs:
    raise SystemExit('unexpected LDO17 layout')
reg.write_text(rs)

# Register only the recovered HWT101 bridge on bus 1 without replacing the OEM2 device arrays.
marker = 'static void k3v2_i2c_devices_init(void)'
if marker not in s:
    raise SystemExit('OEM2 i2c init not found')
if 'hwt101_sn65_bus1' not in s:
    inject = r'''
/* HWT101 / MS1211 SN65DSI83 bridge recovered from the running OEM kernel. */
struct hwt101_sn65dsi83_platform_data { int en_gpio; };
static struct hwt101_sn65dsi83_platform_data hwt101_sn65_pdata = { .en_gpio = 79, };
static struct i2c_board_info hwt101_sn65_bus1[] = {
    { I2C_BOARD_INFO("sn65dsi83", 0x2d), .platform_data = &hwt101_sn65_pdata, },
};

'''
    s = s.replace(marker, inject + marker, 1)
    sig = marker + '\n{'
    repl = sig + '\n\ti2c_register_board_info(1, hwt101_sn65_bus1, ARRAY_SIZE(hwt101_sn65_bus1));'
    if sig not in s:
        raise SystemExit('OEM2 i2c function layout changed')
    s = s.replace(sig, repl, 1)
board.write_text(s)

# Install recovered bridge implementation/table.
src = Path('oem_recovered/display/sn65dsi83_hwt101.c')
tab = Path('oem_recovered/display/sn65dsi83_oem_table.h')
if not src.exists() or not tab.exists():
    raise SystemExit('missing recovered SN65 source/table')
dst = K/'drivers/video/k3'
(dst/'sn65dsi83_hwt101.c').write_text(src.read_text())
(dst/'sn65dsi83_oem_table.h').write_text(tab.read_text())
mk = dst/'Makefile'
ms = mk.read_text()
line = 'obj-y += sn65dsi83_hwt101.o\n'
if line not in ms:
    ms += '\n# HWT101 MS1211 SN65 bridge recovered from OEM\n' + line

# Generic Huawei Makefile links MDW70 and MDY90 unconditionally. OEM HWT101 has only one
# mipi_toshiba_panel_init, so remove the MDY90 object while retaining the other vendor panels.
old_tail = '\tpanel/mipi_cmi_PT045TN07.o \\\n\tpanel/mipi_toshiba_MDY90.o'
if old_tail in ms:
    ms = ms.replace(old_tail, '\tpanel/mipi_cmi_PT045TN07.o')
else:
    ms = re.sub(r'\\\n\s*panel/mipi_toshiba_MDY90\.o\b', '', ms)
if 'panel/mipi_toshiba_MDY90.o' in ms:
    raise SystemExit('failed to remove MDY90 from k3fb objects')
mk.write_text(ms)

# The generic tree incorrectly owns this global in MDY90 although the common EDC/SBL code
# consumes it. Once MDY90 is removed (matching OEM HWT101's single Toshiba initcall), the
# kernel otherwise fails to link. Give the common display layer ownership of the state.
edc = K/'drivers/video/k3/edc_overlay.c'
es = edc.read_text()
extern_decl = 'extern bool sbl_low_power_mode;'
common_def = 'bool sbl_low_power_mode = false;'
if common_def not in es:
    if extern_decl not in es:
        raise SystemExit('sbl_low_power_mode declaration not found in common EDC code')
    es = es.replace(extern_decl, common_def, 1)
edc.write_text(es)
if edc.read_text().count(common_def) != 1:
    raise SystemExit('expected exactly one common sbl_low_power_mode definition')

# Install reconstructed HWT101 NAND controller based on OEM register/IRQ traces.
hinand = Path('scripts/add_hwt101_hinand_v340.py')
if not hinand.exists():
    raise SystemExit('missing NAND helper')
exec(compile(hinand.read_text(), str(hinand), 'exec'), {'__name__':'__main__','__file__':str(hinand)})

# Restore HWT101 TI Wilink radio parity and remove generic U9508 Broadcom BT/Wi-Fi board refs.
radio = Path('scripts/patch_hwt101_ti_radio_v341.py')
if not radio.exists():
    raise SystemExit('missing TI radio parity helper')
_saved_argv = sys.argv[:]
try:
    sys.argv = [str(radio), str(K)]
    exec(compile(radio.read_text(), str(radio), 'exec'), {'__name__':'__main__','__file__':str(radio)})
finally:
    sys.argv = _saved_argv

# Ensure storage stack used by the live device.
cfg = K/'.config'
cs = cfg.read_text()
def set_y(name):
    global cs
    cs = re.sub(r'^CONFIG_'+re.escape(name)+r'=.*\n', '', cs, flags=re.M)
    cs = re.sub(r'^# CONFIG_'+re.escape(name)+r' is not set\n', '', cs, flags=re.M)
    cs += 'CONFIG_'+name+'=y\n'
for opt in ('MTD','MTD_BLOCK','MTD_PARTITIONS','MTD_CMDLINE_PARTS','MTD_NAND','MTD_NAND_IDS','YAFFS_FS','YAFFS_YAFFS2'):
    set_y(opt)
cfg.write_text(cs)

# Refuse a silent return to the wrong board target.
patched = board.read_text()
if 'MACHINE_START(K3V2OEM2, "k3v2oem1")' not in patched:
    raise SystemExit('OEM2 descriptor lost')
if 'hwt101_sn65_bus1' not in patched or '0x2d' not in patched:
    raise SystemExit('SN65 board registration missing')
if 'REGULATOR_SUPPLY("lcd-vcc", "sn65dsi83")' not in reg.read_text():
    raise SystemExit('SN65 LDO17 supply missing')
if not (K/'drivers/mtd/nand/hinand_hwt101.c').exists():
    raise SystemExit('HWT101 hinand source missing')
if 'panel/mipi_toshiba_MDY90.o' in mk.read_text():
    raise SystemExit('MDY90 unexpectedly returned to k3fb objects')
if edc.read_text().count(common_def) != 1:
    raise SystemExit('common sbl_low_power_mode definition lost')
for bp in (K/'arch/arm/mach-k3v2/board-k3v2oem1.c', K/'arch/arm/mach-k3v2/board-k3v2oem2.c'):
    bs = bp.read_text()
    if re.search(r'^\s*&(?:btbcm_device|bcm_bluesleep_device),', bs, flags=re.M):
        raise SystemExit('Broadcom BT board reference survived in ' + bp.name)
print('HWT101 V3.41 OEM2 + SN65 + NAND + TI radio parity + common SBL board patch: OK')
