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
print('V3.56 PANEL PARITY patch installed')
print('PANEL_XRES=1280')
print('PANEL_YRES=800')
print('PANEL_ORIENTATION=LANDSCAPE')
print('DONOR_TIMINGS=UNCHANGED')
print('CHECKPOINT=NONE')
print('SWAP_ZRAM=UNCHANGED_OFF')
