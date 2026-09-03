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
def clear(name):
    global cs
    cs = re.sub(r'^CONFIG_'+re.escape(name)+r'=.*\n', '', cs, flags=re.M)
    cs = re.sub(r'^# CONFIG_'+re.escape(name)+r' is not set\n', '', cs, flags=re.M)
def set_y(name):
    global cs
    clear(name)
    cs += 'CONFIG_'+name+'=y\n'
def set_m(name):
    global cs
    clear(name)
    cs += 'CONFIG_'+name+'=m\n'
def set_n(name):
    global cs
    clear(name)
    cs += '# CONFIG_'+name+' is not set\n'

# OEM kernel has TI Shared Transport built in, but only the wl12xx platform-data shim
# built in. Keep the old wl12xx/mac80211 drivers modular so their implementation does
# not enter zImage while satisfying WL12XX_PLATFORM_DATA's Kconfig dependency.
set_y('TI_ST')
for opt in ('MAC80211', 'WL12XX_MENU', 'WL12XX', 'WL12XX_SDIO'):
    set_m(opt)
set_y('WL12XX_PLATFORM_DATA')

# Generic U9508 Broadcom Wi-Fi/BT is not part of HWT101. Keep BCM GPS untouched:
# the live OEM kernel does contain the k3_gps_bcm driver.
for opt in ('BCMDHD', 'BCMDHD_BCM', 'BT_BCM_POWER'):
    set_n(opt)

cfg.write_text(cs)
print('HWT101 TI radio parity: TI_ST + wl12xx pdata builtin, wl12xx SDIO modular, Broadcom DHD/BT disabled')
