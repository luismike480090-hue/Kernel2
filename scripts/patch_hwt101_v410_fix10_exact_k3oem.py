#!/usr/bin/env python3
from pathlib import Path
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else "kernel")
total = root / "drivers/huawei/hsad/config_total_product.c"
out = root / "drivers/huawei/hsad/auto-generate/hw_hwt101_fix10_k3oem_configs.c"

if not total.exists():
    raise SystemExit(f"missing required source: {total}")

out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(r'''/* Reconstructed byte-for-byte in semantics from the known-good
 * HWT101 FIX10 kernel image. Do not replace with the public hw_k3oem_configs.c:
 * that public profile has different values and is NOT the HWT101 FIX10 profile.
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
inc = '#include "auto-generate/hw_hwt101_fix10_k3oem_configs.c"'
if inc not in s:
    # place after the last include to avoid depending on a particular donor list
    lines=s.splitlines()
    last=-1
    for i,line in enumerate(lines):
        if line.startswith('#include '):
            last=i
    if last < 0:
        raise SystemExit("no include anchor in config_total_product.c")
    lines.insert(last+1, inc)
    s='\n'.join(lines)+'\n'

entry='    &config_common_hwt101_fix10_k3oem,'
if entry not in s:
    marker='hw_ver_total_configs[]'
    p=s.find(marker)
    if p < 0:
        raise SystemExit("hw_ver_total_configs array missing")
    brace=s.find('{',p)
    if brace < 0:
        raise SystemExit("hw_ver_total_configs opening brace missing")
    s=s[:brace+1]+'\n'+entry+s[brace+1:]

total.write_text(s)

ts=total.read_text()
ks=out.read_text()
checks = {
    "include": inc in ts,
    "entry": entry in ts,
    "boardid0": ".board_id = 0x00" in ks,
    "audience_none": '"audio/audience", (const unsigned int)(unsigned int*)"NONE"' in ks,
    "dual_mic_0": '"audio/dual_mic", (unsigned int)0' in ks,
    "keypad_1": '"keypad/keypad_type", (unsigned int)1' in ks,
    "sensor_1": '"sensor/sensor_type", (unsigned int)1' in ks,
    "iomux_0": '"iomux/iomux_type", (unsigned int)0' in ks,
    "product_k3oem": '"product/name", (const unsigned int)(unsigned int*)"k3oem"' in ks,
}
bad=[k for k,v in checks.items() if not v]
if bad:
    raise SystemExit("V410 exact profile gate failed: "+",".join(bad))

print("V410_FIX10_EXACT_K3OEM=PASS")
print("BASE=V407B_HARDWARE_PASS")
print("BOARD_ID=0x00")
print("PAIR_COUNT=21")
print("AUDIENCE=NONE")
print("DUAL_MIC=0")
print("KEYPAD_TYPE=1")
print("SENSOR_TYPE=1")
print("IOMUX_TYPE=0")
print("PRODUCT=k3oem")
print("PUBLIC_K3OEM_PROFILE=NOT_USED")
\n# trigger build\n