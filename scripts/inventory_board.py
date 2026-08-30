#!/usr/bin/env python3
from pathlib import Path
import re,sys
k=Path(sys.argv[1] if len(sys.argv)>1 else 'kernel')
out=Path(sys.argv[2] if len(sys.argv)>2 else 'BOARD-I2C-INVENTORY.txt')
patterns=[r'k3v2oem1_i2c_\d+_boardinfo',r'i2c_register_board_info',r'I2C_BOARD_INFO',r'sn65dsi83',r'bq2419x',r'Goodix',r'goodix',r'ft5x0x']
lines=[]
for p in k.rglob('*.[ch]'):
    try:t=p.read_text(errors='ignore')
    except:continue
    hit=False
    for pat in patterns:
        if re.search(pat,t): hit=True; break
    if not hit: continue
    for i,l in enumerate(t.splitlines(),1):
        if any(re.search(pat,l) for pat in patterns):
            lines.append(f'{p.relative_to(k)}:{i}: {l.strip()}')
out.write_text('\n'.join(lines)+'\n')
print(f'wrote {out} with {len(lines)} matches')
