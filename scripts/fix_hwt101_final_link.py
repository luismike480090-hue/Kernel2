#!/usr/bin/env python3
from pathlib import Path
import re, sys

if len(sys.argv) != 3:
    print('usage: fix_hwt101_final_link.py <kernel> <huawei-reference>')
    sys.exit(2)
K=Path(sys.argv[1]).resolve(); R=Path(sys.argv[2]).resolve()

def rd(p): return p.read_text(errors='ignore')
def wr(p,s): p.write_text(s); print('PATCHED', p.relative_to(K) if str(p).startswith(str(K)) else p)
def fn_extract(text,name):
    m=re.search(r'(?m)^[^\n;{}]*\b'+re.escape(name)+r'\s*\([^;{}]*\)\s*\{', text)
    if not m: raise RuntimeError('function not found: '+name)
    start=m.start(); brace=text.find('{',m.start(),m.end()+1); depth=0
    for i in range(brace,len(text)):
        if text[i]=='{': depth+=1
        elif text[i]=='}':
            depth-=1
            if depth==0: return text[start:i+1]
    raise RuntimeError('unterminated function: '+name)

def force_obj(makefile,obj,comment):
    p=K/makefile; t=rd(p)
    if obj not in t:
        t+='\nobj-y += '+obj+'  # '+comment+'\n'; wr(p,t)

# Remove known false-positive providers from older resolver versions.
for rel,obj in [('drivers/mfd/Makefile','da903x.o'),('arch/arm/mach-omap2/Makefile','pm-debug.o')]:
    p=K/rel
    if p.exists():
        t=rd(p); lines=t.splitlines(); n=[x for x in lines if not(obj in x and 'HWT101 exact link provider' in x)]
        if n!=lines: wr(p,'\n'.join(n)+'\n')

# notifier_list: provide ONLY the ABI symbol needed by the imported charger code.
# Do NOT import the complete Huawei bq_bci_battery.c: that donor core depends on
# POWER_SUPPLY_PROP_CAPACITY_RM/FCC which do not exist in the S10 power_supply ABI.
pmk=K/'drivers/power/Makefile'
pmt=rd(pmk)
lines=pmt.splitlines()
clean=[]
for line in lines:
    if 'bq_bci_battery.o' in line and ('HWT101 OEM charging notifier provider' in line or 'HWT101 exact link provider' in line):
        print('REMOVED forced donor core:', line.strip())
        continue
    clean.append(line)
if clean != lines:
    wr(pmk,'\n'.join(clean)+'\n')

notifier_compat=K/'drivers/power/hwt101_bq_notifier_compat.c'
notifier_compat.write_text('''/* HWT101 minimal Huawei charging notifier ABI.\n * Keep the native S10 power-supply core untouched. */\n#include <linux/notifier.h>\n\nBLOCKING_NOTIFIER_HEAD(notifier_list);\n''')
print('PATCHED',notifier_compat.relative_to(K))
force_obj('drivers/power/Makefile','hwt101_bq_notifier_compat.o','HWT101 OEM charging notifier ABI')

# IPPS ABI: donor Huawei has one extra command at the end of enum ipps_cmd_type.
ipps_h=K/'include/linux/ipps.h'; ih=rd(ipps_h)
if 'IPPS_UPDATE_POWER_CAPACITY' not in ih:
    em=re.search(r'(enum\s+ipps_cmd_type\s*\{)(.*?)(\n\s*\};)',ih,re.S)
    if not em: raise RuntimeError('enum ipps_cmd_type not found in S10 include/linux/ipps.h')
    body=em.group(2)
    if not body.rstrip().endswith(','): body=body.rstrip()+','
    body += '\n\tIPPS_UPDATE_POWER_CAPACITY,'
    ih=ih[:em.start(2)]+body+ih[em.end(2):]
    wr(ipps_h,ih)

# Exact Huawei IPPS implementation.
dst=K/'arch/arm/mach-k3v2/ipps-core.c'; src=R/'arch/arm/mach-k3v2/ipps-core.c'; t=rd(dst)
if not re.search(r'(?m)^\s*int\s+ipps_update_power_capacity\s*\(',t):
    t+='\n\n/* HWT101 exact Huawei K3V2 API */\n'+fn_extract(rd(src),'ipps_update_power_capacity')+'\n'; wr(dst,t)

# Public prototype matching the donor ABI.
ih=rd(ipps_h)
if not re.search(r'\bipps_update_power_capacity\s*\(',ih):
    proto='\nint ipps_update_power_capacity(struct ipps_client *client, unsigned int object,\n\t\t\tint *param);\n'
    pos=ih.rfind('#endif')
    if pos<0: raise RuntimeError('#endif not found in S10 include/linux/ipps.h')
    ih=ih[:pos]+proto+'\n'+ih[pos:]
    wr(ipps_h,ih)

# Recovery compatibility getter. Avoid importing donor-private boot-state storage.
dst=K/'arch/arm/mach-k3v2/common.c'; t=rd(dst)
if not re.search(r'(?m)^\s*unsigned\s+int\s+get_boot_into_recovery_flag\s*\(',t):
    block='''\n\n/* HWT101 recovery compatibility API. */\nstatic unsigned int hwt101_enter_recovery_flag;\nunsigned int get_boot_into_recovery_flag(void)\n{\n    return hwt101_enter_recovery_flag;\n}\n'''
    t+=block; wr(dst,t)

# wakeup_timer_seconds: exact K3V2 donor declaration. Never pull OMAP pm-debug.
wake_src=R/'arch/arm/mach-k3v2/k3v2_wakeup_timer.c'; s=rd(wake_src)
vm=re.search(r'(?m)^\s*(?!extern\b)(?:static\s+)?(?:unsigned\s+int|u32)\s+wakeup_timer_seconds\s*(?:=\s*[^;\n]+)?\s*;',s)
if not vm: raise RuntimeError('exact K3V2 wakeup_timer_seconds not found')

# FSA880-safe HIUSB ABI compatibility. Do not enable CONFIG_SUPPORT_MICRO_USB_PORT.
compat=K/'arch/arm/mach-k3v2/hwt101_oem_compat.c'
compat.write_text('''/* HWT101 K3V2 compatibility for OEM charging glue. */\n#include <linux/kernel.h>\n#include <linux/types.h>\n#include <linux/notifier.h>\n#include <linux/usb/hiusb_android.h>\n\n%s\n\nstatic ATOMIC_NOTIFIER_HEAD(hwt101_charger_type_notifier_head);\nstatic int hwt101_charger_type = CHARGER_REMOVED;\nint get_charger_name(void) { return hwt101_charger_type; }\nint hiusb_charger_registe_notifier(struct notifier_block *nb) { return atomic_notifier_chain_register(&hwt101_charger_type_notifier_head, nb); }\nint hiusb_charger_unregiste_notifier(struct notifier_block *nb) { return atomic_notifier_chain_unregister(&hwt101_charger_type_notifier_head, nb); }\n''' % vm.group(0).strip())
print('PATCHED',compat.relative_to(K))
force_obj('arch/arm/mach-k3v2/Makefile','hwt101_oem_compat.o','HWT101 final OEM glue')

# PRE-FLIGHT: validate historical blockers before spending build time.
checks=[]
checks.append(('notifier_list minimal ABI', 'BLOCKING_NOTIFIER_HEAD(notifier_list)' in rd(notifier_compat)))
checks.append(('donor bq_bci not forced', not any('bq_bci_battery.o' in x and 'HWT101' in x for x in rd(pmk).splitlines())))
checks.append(('IPPS_UPDATE_POWER_CAPACITY enum', 'IPPS_UPDATE_POWER_CAPACITY' in rd(ipps_h)))
checks.append(('ipps_update_power_capacity', bool(re.search(r'\bipps_update_power_capacity\s*\(',rd(K/'arch/arm/mach-k3v2/ipps-core.c')))))
checks.append(('ipps_update_power_capacity prototype', bool(re.search(r'\bipps_update_power_capacity\s*\(',rd(ipps_h)))))
checks.append(('get_boot_into_recovery_flag', bool(re.search(r'\bget_boot_into_recovery_flag\s*\(',rd(K/'arch/arm/mach-k3v2/common.c')))))
checks.append(('wakeup_timer_seconds', 'wakeup_timer_seconds' in rd(compat)))
checks.append(('get_charger_name', 'int get_charger_name(void)' in rd(compat)))
checks.append(('hiusb_charger_registe_notifier', 'hiusb_charger_registe_notifier' in rd(compat)))
checks.append(('hiusb_charger_unregiste_notifier', 'hiusb_charger_unregiste_notifier' in rd(compat)))
failed=[n for n,ok in checks if not ok]
if failed: raise RuntimeError('V3.27 preflight failed: '+', '.join(failed))

Path('HWT101-FINAL-LINK-PATCH.txt').write_text('''HWT101 V3.27 minimal final-link repair\nnotifier_list: standalone BLOCKING_NOTIFIER_HEAD ABI; full donor bq_bci core intentionally NOT imported\npower_supply ABI: S10 native enum preserved; no CAPACITY_RM/FCC additions\nIPPS_UPDATE_POWER_CAPACITY: exact Huawei donor ABI ordering\nipps_update_power_capacity: exact donor implementation plus public prototype\nget_boot_into_recovery_flag: stable compatibility getter\nwakeup_timer_seconds: exact K3V2 declaration\nHIUSB ABI: FSA880-safe compatibility provider; CONFIG_SUPPORT_MICRO_USB_PORT remains disabled\npreflight: rejects reintroduction of forced donor bq_bci_battery.o\n''')
print(Path('HWT101-FINAL-LINK-PATCH.txt').read_text())
