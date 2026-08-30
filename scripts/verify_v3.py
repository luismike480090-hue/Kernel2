#!/usr/bin/env python3
from pathlib import Path
import subprocess,sys,re
k=Path(sys.argv[1] if len(sys.argv)>1 else 'kernel')
rep=[]
def add(ok,name,detail=''):
    rep.append((ok,name,detail))
    print(('OK   ' if ok else 'MISS ')+name+((' :: '+detail) if detail else ''))

z=k/'arch/arm/boot/zImage'; sm=k/'System.map'; vm=k/'vmlinux'; cfg=k/'.config'
add(z.exists() and z.stat().st_size>0,'zImage',str(z.stat().st_size if z.exists() else 0))
text=sm.read_text(errors='ignore') if sm.exists() else ''
for s in ['sys_swapon','sys_swapoff','zram_init','xv_malloc','lzo1x_1_compress','hwt101_sn65_probe']:
    add(bool(re.search(r'\b'+re.escape(s)+r'$',text,re.M)),s)

# Kernelrelease MUST exactly match OEM modules.
try:
    kr=subprocess.check_output(['make','-s','kernelrelease'],cwd=k,text=True).strip()
except Exception as e:
    kr=f'ERROR:{e}'
add(kr=='3.0.8-g883717a-dirty','kernelrelease exact',kr)

# Hardware parity status: distinguish present from still missing.
checks={
 'BQ2419X':'bq2419x_charger_probe',
 'GOODIX':'goodix_ts_probe',
 'FT5X0X':'ft5x0x_ts_probe',
 'GC0339':'gc0339_init',
 'S5K5CAG':'s5k5cag_init',
}
for n,s in checks.items():
    add(bool(re.search(r'\b'+re.escape(s)+r'$',text,re.M)),n,s)

# Flashability gate: display + memory + exact release are mandatory, and active touch/charger/cameras should be present.
required=['sys_swapon','sys_swapoff','zram_init','xv_malloc','lzo1x_1_compress','hwt101_sn65_probe','bq2419x_charger_probe','goodix_ts_probe','gc0339_init','s5k5cag_init']
missing=[s for s in required if not re.search(r'\b'+re.escape(s)+r'$',text,re.M)]
flashable=(kr=='3.0.8-g883717a-dirty' and not missing and z.exists() and z.stat().st_size>0)
Path('FLASHABILITY.txt').write_text('FLASHABLE=YES\n' if flashable else 'FLASHABLE=NO\nMISSING='+','.join(missing)+'\nKERNELRELEASE='+kr+'\n')
# Do not fail build for parity-missing: artifact is useful for next correction. Fail only if core memory/display/release broken.
core=['sys_swapon','sys_swapoff','zram_init','xv_malloc','lzo1x_1_compress','hwt101_sn65_probe']
corebad=[s for s in core if not re.search(r'\b'+re.escape(s)+r'$',text,re.M)]
if kr!='3.0.8-g883717a-dirty' or corebad or not z.exists() or not z.stat().st_size:
    sys.exit(2)
