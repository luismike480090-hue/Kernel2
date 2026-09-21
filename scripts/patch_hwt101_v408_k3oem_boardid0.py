#!/usr/bin/env python3
from pathlib import Path
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else "kernel")
boardids = root / "include/hsad/config_boardids.h"
total = root / "drivers/huawei/hsad/config_total_product.c"
k3oem = root / "drivers/huawei/hsad/auto-generate/hw_k3oem_configs.c"

for p in (boardids, total, k3oem):
    if not p.exists():
        raise SystemExit(f"missing required source: {p}")

s = boardids.read_text()
if "BOARD_ID_K3OEM" not in s:
    marker = "#endif"
    if marker not in s:
        raise SystemExit("config_boardids.h missing #endif")
    s = s.replace(marker, "#define BOARD_ID_K3OEM 0x00\n" + marker, 1)
    boardids.write_text(s)

s = total.read_text()
inc = '#include "auto-generate/hw_k3oem_configs.c"'
if inc not in s:
    anchor = '#include <hsad/config_boardids.h>'
    if anchor not in s:
        raise SystemExit("config_total_product.c include anchor missing")
    s = s.replace(anchor, anchor + "\n" + inc, 1)

entry = "    &config_common_k3oem,"
if entry not in s:
    anchor = "struct board_id_general_struct  *hw_ver_total_configs[] = \n{\n"
    if anchor not in s:
        anchor = "struct board_id_general_struct *hw_ver_total_configs[] =\n{\n"
    if anchor not in s:
        raise SystemExit("hw_ver_total_configs array anchor missing")
    s = s.replace(anchor, anchor + entry + "\n", 1)

total.write_text(s)

# Static sanity checks.
bs = boardids.read_text()
ts = total.read_text()
ks = k3oem.read_text()
assert "#define BOARD_ID_K3OEM 0x00" in bs
assert inc in ts
assert entry in ts
assert '.board_id=BOARD_ID_K3OEM' in ks
assert '"product/name"' in ks and '"k3oem"' in ks
assert '"iomux/iomux_type", (unsigned int)0' in ks

print("V408_K3OEM_PATCH=PASS")
print("BOARD_ID_K3OEM=0x00")
print("PROFILE=config_common_k3oem")
print("PRODUCT=k3oem")
print("IOMUX_TYPE=0")

# trigger V4.08 workflow
