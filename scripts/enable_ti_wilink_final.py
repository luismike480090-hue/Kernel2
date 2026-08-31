#!/usr/bin/env python3
from pathlib import Path
import shutil, sys, re

if len(sys.argv) != 3:
    print('usage: enable_ti_wilink_final.py <kernel> <donor>')
    sys.exit(2)

K=Path(sys.argv[1]); R=Path(sys.argv[2])
report=[]
def say(s):
    print(s); report.append(s)

def copytree(src,dst):
    if not src.exists():
        raise SystemExit('missing donor path: '+str(src))
    if dst.exists(): shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src,dst)

# Exact TI Shared Transport from the same Huawei K3V2 donor used by V3.29.
copytree(R/'drivers/misc/ti-st', K/'drivers/misc/ti-st')
(K/'include/linux').mkdir(parents=True, exist_ok=True)
shutil.copy2(R/'include/linux/ti_wilink_st.h', K/'include/linux/ti_wilink_st.h')
shutil.copy2(R/'drivers/bluetooth/btwilink.c', K/'drivers/bluetooth/btwilink.c')
say('TI-ST sources: exact K3V2 donor imported')
say('BT WiLink source: exact K3V2 donor imported')

# Wire TI-ST into misc build/Kconfig without replacing unrelated base files.
mf=K/'drivers/misc/Makefile'
t=mf.read_text(errors='ignore')
if 'ti-st/' not in t:
    t += '\n# HWT101_FINAL_TI_ST\nobj-y += ti-st/\n'
    mf.write_text(t)

kc=K/'drivers/misc/Kconfig'
t=kc.read_text(errors='ignore')
if 'drivers/misc/ti-st/Kconfig' not in t:
    t += '\n# HWT101_FINAL_TI_ST\nsource "drivers/misc/ti-st/Kconfig"\n'
    kc.write_text(t)

# Wire btwilink into the native Bluetooth tree.
bmf=K/'drivers/bluetooth/Makefile'
t=bmf.read_text(errors='ignore')
if 'CONFIG_BT_WILINK' not in t:
    t += '\n# HWT101_FINAL_BT_WILINK\nobj-$(CONFIG_BT_WILINK) += btwilink.o\n'
    bmf.write_text(t)

bkc=K/'drivers/bluetooth/Kconfig'
t=bkc.read_text(errors='ignore')
if 'config BT_WILINK' not in t:
    t += '''\n# HWT101_FINAL_BT_WILINK\nconfig BT_WILINK\n\ttristate "Texas Instruments WiLink7 driver"\n\tdepends on TI_ST\n\tdefault y\n\thelp\n\t  Bluetooth protocol driver for TI WiLink shared transport.\n'''
    bkc.write_text(t)

# Set only the required native K3V2 options. oldnoconfig will resolve dependencies.
cfg=K/'.config'
text=cfg.read_text(errors='ignore')

def setcfg(name,val='y'):
    global text
    rx=re.compile(r'(?m)^(?:'+re.escape(name)+r'=.*|# '+re.escape(name)+r' is not set)$')
    line=f'{name}={val}'
    if rx.search(text): text=rx.sub(line,text)
    else: text += '\n'+line+'\n'

for name in ['CONFIG_MODULES','CONFIG_FW_LOADER','CONFIG_RFKILL','CONFIG_BT','CONFIG_TI_ST','CONFIG_BT_WILINK']:
    setcfg(name,'y')
cfg.write_text(text)

say('Enabled: CONFIG_TI_ST=y CONFIG_BT_WILINK=y')
say('Preserved: existing Wi-Fi modules in /system; no duplicate wl18xx/wlcore built into kernel')
say('FT5X0X intentionally NOT enabled: HWT101 runtime evidence identifies Goodix as active touch controller')
Path('HWT101-FINAL-TI-WILINK.txt').write_text('\n'.join(report)+'\n')
