#!/usr/bin/env python3
from pathlib import Path
import sys

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('kernel')
p = root / 'firmware/Makefile'
s = p.read_text(errors='ignore')
line = 'fw-shipped-y += cyttsp4_fw.bin'
if line not in s:
    raise SystemExit('ERROR: cyttsp4 unconditional firmware line not found')
s = s.replace(line, '# HWT360 OEM parity: CYTTSP4 absent from HWT101 OEM; do not embed cyttsp4_fw.bin', 1)
p.write_text(s)
print('HWT360_FIRMWARE_PARITY=PASS')
print('CYTTSP4_FIRMWARE_EMBED=REMOVED')
