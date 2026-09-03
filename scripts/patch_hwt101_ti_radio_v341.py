#!/usr/bin/env python3
from pathlib import Path
import re, sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch_hwt101_ti_radio_v341.py <kernel-root>')
K = Path(sys.argv[1])

# The running HWT101 OEM kernel exposes TI Shared Transport / wl12xx platform-data
# symbols and does not expose Broadcom DHD or Broadcom BT platform devices.
for name in ('board-k3v2oem1.c', 'board-k3v2oem2.c'):
    p = K/'arch/arm/mach-k3v2'/name
    s = p.read_text()
    before = s
    s = re.sub(r'^\s*&btbcm_device,\s*\n', '', s, flags=re.M)
    s = re.sub(r'^\s*&bcm_bluesleep_device,\s*\n', '', s, flags=re.M)
    if s == before:
        raise SystemExit('Broadcom BT device references not found in ' + name)
    if re.search(r'^\s*&(?:btbcm_device|bcm_bluesleep_device),', s, flags=re.M):
        raise SystemExit('Broadcom BT device reference survived in ' + name)
    p.write_text(s)

cfg = K/'.config'
cs = cfg.read_text()
def set_y(name):
    global cs
    cs = re.sub(r'^CONFIG_'+re.escape(name)+r'=.*\n', '', cs, flags=re.M)
    cs = re.sub(r'^# CONFIG_'+re.escape(name)+r' is not set\n', '', cs, flags=re.M)
    cs += 'CONFIG_'+name+'=y\n'
def set_n(name):
    global cs
    cs = re.sub(r'^CONFIG_'+re.escape(name)+r'=.*\n', '', cs, flags=re.M)
    cs = re.sub(r'^# CONFIG_'+re.escape(name)+r' is not set\n', '', cs, flags=re.M)
    cs += '# CONFIG_'+name+' is not set\n'

# TI connectivity present in OEM/FIX10.
for opt in ('TI_ST', 'WL12XX_PLATFORM_DATA'):
    set_y(opt)

# Generic U9508 Broadcom Wi-Fi/BT is not part of HWT101.
for opt in ('BCMDHD', 'BCMDHD_BCM', 'BT_BCM_POWER'):
    set_n(opt)

cfg.write_text(cs)
print('HWT101 TI radio parity: TI_ST/WL12XX pdata enabled; Broadcom DHD/BT board refs disabled')
