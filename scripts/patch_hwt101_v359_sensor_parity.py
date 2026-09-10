#!/usr/bin/env python3
from pathlib import Path
import sys

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("kernel")
p = root / "drivers/huawei/device/sensor_info.c"
text = p.read_text()
old = "if(set_selftest(val) || set_selftest_lm330(val))"
new = "if(set_selftest(val)) /* HWT359: OEM HWT101 has no LSM330 selftest path */"
if old not in text:
    raise SystemExit("ERROR: expected unconditional LSM330 selftest call not found")
text = text.replace(old, new, 1)
p.write_text(text)
print("HWT359_SENSOR_PARITY=PASS")
print("REMOVED_DANGLING_CALL=set_selftest_lm330")
