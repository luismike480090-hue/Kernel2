#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch_hwt101_v356_panel_parity.py <kernel-root>')

K = Path(sys.argv[1])
p = K / 'drivers/video/k3/panel/mipi_toshiba_MDW70_V001.c'
s = p.read_text(errors='ignore')

# HWT101 OEM runtime facts:
#   fb0 name         = k3fb0
#   fb0 mode         = 1280x800
#   fb0 virtual_size = 1280x3200 (4 pages)
#   fb0 bpp          = 32
#   fb0 stride       = 5120
# The recovered SN65DSI83 table independently encodes
# CHA_ACTIVE_LINE_LENGTH=1280 and CHA_VERTICAL_DISPLAY_SIZE=800.
# The public MDW70 donor is a 720x1280 portrait phone panel and MUST NOT be
# passed unchanged to K3FB on the T101 tablet.

repls = [
    ('pinfo->xres = 720;', 'pinfo->xres = 1280;'),
    ('pinfo->yres = 1280;', 'pinfo->yres = 800;'),
    ('pinfo->orientation = LCD_PORTRAIT;', 'pinfo->orientation = LCD_LANDSCAPE;'),
]
for old, new in repls:
    if old not in s:
        raise SystemExit('panel anchor missing: ' + old)
    s = s.replace(old, new, 1)

# Keep the donor electrical/timing fields unchanged in this experiment.
# V3.56 isolates only the proven OEM geometry/orientation mismatch.
# Do not guess clk_rate, DSI bit clock, porches, GPIOs, or regulator values.

# Add an unmistakable build/runtime marker without touching initcall flow.
anchor = 'static int __devinit toshiba_probe(struct platform_device *pdev)\n{'
if anchor not in s:
    raise SystemExit('toshiba_probe anchor missing')
s = s.replace(anchor, anchor + '\n\tprintk(KERN_WARNING "HWT356 PANEL_PARITY 1280x800 LANDSCAPE\\n");', 1)

for required in (
    'pinfo->xres = 1280;',
    'pinfo->yres = 800;',
    'pinfo->orientation = LCD_LANDSCAPE;',
    'HWT356 PANEL_PARITY 1280x800 LANDSCAPE',
):
    if required not in s:
        raise SystemExit('V3.56 gate failed: ' + required)

p.write_text(s)

# V3.59 OEM sensor parity:
# The pinned donor revision calls set_selftest_lm330() unconditionally from
# sensor_info.c. Once the LSM330 donor driver is disabled this leaves an
# undefined reference at final link. Later upstream source already removed
# this unconditional call. HWT101 OEM kallsyms also has no LSM330 path.
sp = K / 'drivers/huawei/device/sensor_info.c'
ss = sp.read_text(errors='ignore')
old = 'if(set_selftest(val) || set_selftest_lm330(val))'
new = 'if(set_selftest(val)) /* HWT359: OEM HWT101 has no LSM330 selftest path */'
if old not in ss:
    raise SystemExit('sensor_info LSM330 selftest anchor missing')
ss = ss.replace(old, new, 1)
sp.write_text(ss)

# V3.60 modem prune dependency closure:
# MODEM_BOOT_QSC6085 owns get_resume_flag()/clear_resume_flag(). The donor
# n_gsm_qsc line discipline references those helpers when UART sleep control
# is enabled. Once all cellular modem boot drivers are removed, keeping any
# vendor GSM-MUX discipline is both dead tablet code and can make final link
# impossible. HWT101 has no cellular modem path, so remove the full GSM-MUX
# family after all earlier config edits and immediately before oldnoconfig.
cfgp = K / '.config'
cfg = cfgp.read_text(errors='ignore')
for name in ('N_GSM', 'N_GSM_MTK', 'N_GSM_QSC', 'N_GSM_BALONG'):
    lines = []
    for line in cfg.splitlines():
        if line.startswith('CONFIG_' + name + '=') or line == '# CONFIG_' + name + ' is not set':
            continue
        lines.append(line)
    lines.append('# CONFIG_' + name + ' is not set')
    cfg = '\n'.join(lines) + '\n'
cfgp.write_text(cfg)

print('V3.56 PANEL PARITY patch installed')
print('PANEL_XRES=1280')
print('PANEL_YRES=800')
print('PANEL_ORIENTATION=LANDSCAPE')
print('DONOR_TIMINGS=UNCHANGED')
print('HWT359_LSM330_DANGLING_CALL=REMOVED')
print('HWT360_GSM_MUX_FAMILY=DISABLED')
print('CHECKPOINT=NONE')
print('SWAP_ZRAM=UNCHANGED_OFF')
