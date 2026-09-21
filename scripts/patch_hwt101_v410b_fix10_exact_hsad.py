#!/usr/bin/env python3
from pathlib import Path
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else "kernel")
total = root / "drivers/huawei/hsad/auto-generate/config_total_product.c"
out = root / "drivers/huawei/hsad/auto-generate/hw_hwt101_fix10_k3oem_configs.c"

if not total.exists():
    raise SystemExit(f"missing compiled HSAD table: {total}")

out.write_text(r'''/* Exact HWT101/FIX10 boardid=0 common profile reconstructed from
 * the known-good FIX10 kernel image. This is intentionally NOT the generic
 * public hw_k3oem_configs.c, whose values differ from the T101 OEM kernel.
 */
#include <hsad/configdata.h>
#include <hsad/config_general_struct.h>

config_pair hw_hwt101_fix10_k3oem_configs[] = {
    {"arch/arch_type", (unsigned int)1, E_CONFIG_DATA_TYPE_INT },
    {"audio/audience", (const unsigned int)(unsigned int*)"NONE", E_CONFIG_DATA_TYPE_STRING },
    {"audio/digital_mic", (unsigned int)0, E_CONFIG_DATA_TYPE_INT },
    {"audio/dual_mic", (unsigned int)0, E_CONFIG_DATA_TYPE_INT },
    {"audio/hs_keys", (unsigned int)1, E_CONFIG_DATA_TYPE_INT },
    {"audio/hs_pa", (const unsigned int)(unsigned int*)"NONE", E_CONFIG_DATA_TYPE_STRING },
    {"audio/hsd_invert", (unsigned int)1, E_CONFIG_DATA_TYPE_INT },
    {"audio/spk_pa", (const unsigned int)(unsigned int*)"NONE", E_CONFIG_DATA_TYPE_STRING },
    {"audio/spk_route", (const unsigned int)(unsigned int*)"SPK", E_CONFIG_DATA_TYPE_STRING },
    {"battery/battery_type", (unsigned int)0, E_CONFIG_DATA_TYPE_INT },
    {"board/board_type", (unsigned int)0, E_CONFIG_DATA_TYPE_INT },
    {"camera/faceIgnoreCount", (unsigned int)9, E_CONFIG_DATA_TYPE_INT },
    {"camera/primary_sensor", (unsigned int)90, E_CONFIG_DATA_TYPE_INT },
    {"camera/secondary_sensor", (unsigned int)90, E_CONFIG_DATA_TYPE_INT },
    {"iomux/iomux_type", (unsigned int)0, E_CONFIG_DATA_TYPE_INT },
    {"keypad/keypad_type", (unsigned int)1, E_CONFIG_DATA_TYPE_INT },
    {"lcd/lcd_type", (unsigned int)0, E_CONFIG_DATA_TYPE_INT },
    {"product/name", (const unsigned int)(unsigned int*)"k3oem", E_CONFIG_DATA_TYPE_STRING },
    {"sensor/sensor_type", (unsigned int)1, E_CONFIG_DATA_TYPE_INT },
    {"touchscreen/touchscreen_type", (unsigned int)0, E_CONFIG_DATA_TYPE_INT },
    {"usbphy/usbphy_type", (unsigned int)0, E_CONFIG_DATA_TYPE_INT },
    {0, 0, 0}
};

struct board_id_general_struct config_common_hwt101_fix10_k3oem = {
    .name = COMMON_MODULE_NAME,
    .board_id = 0x00,
    .data_array = {.config_pair_ptr = hw_hwt101_fix10_k3oem_configs},
    .list = {NULL, NULL},
};
''')

s = total.read_text()
inc = '#include "hw_hwt101_fix10_k3oem_configs.c"'
if inc not in s:
    lines=s.splitlines()
    last=-1
    for i,line in enumerate(lines):
        if line.startswith('#include "hw_'):
            last=i
    if last < 0:
        raise SystemExit("compiled HSAD include anchor missing")
    lines.insert(last+1, inc)
    s='\n'.join(lines)+'\n'

entry='    &config_common_hwt101_fix10_k3oem, // HWT101 FIX10 exact boardid 0 common'
if entry not in s:
    marker='struct board_id_general_struct  *hw_ver_total_configs[]'
    p=s.find(marker)
    if p < 0:
        raise SystemExit("hw_ver_total_configs declaration missing")
    brace=s.find('{',p)
    if brace < 0:
        raise SystemExit("hw_ver_total_configs opening brace missing")
    # Put the exact boardid0 common first. No other compiled profile has boardid 0.
    s=s[:brace+1]+'\n'+entry+s[brace+1:]

total.write_text(s)

ts=total.read_text()
ks=out.read_text()
assert inc in ts
assert entry in ts
assert ".board_id = 0x00" in ks
assert '"audio/audience", (const unsigned int)(unsigned int*)"NONE"' in ks
assert '"audio/dual_mic", (unsigned int)0' in ks
assert '"camera/secondary_sensor", (unsigned int)90' in ks
assert '"iomux/iomux_type", (unsigned int)0' in ks
assert '"keypad/keypad_type", (unsigned int)1' in ks
assert '"sensor/sensor_type", (unsigned int)1' in ks
assert '"product/name", (const unsigned int)(unsigned int*)"k3oem"' in ks
assert sum(1 for line in ks.splitlines() if line.strip().startswith('{"')) == 21

print("V410B_FIX10_EXACT_HSAD=PASS")
print("PATCHED_FILE=drivers/huawei/hsad/auto-generate/config_total_product.c")
print("BOARD_ID=0x00")
print("PAIR_COUNT=21")
print("PUBLIC_K3OEM_PROFILE=NOT_USED")
print("BASE=V407B_HARDWARE_PASS")
