#!/usr/bin/env python3
from pathlib import Path
import re, sys, shutil

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

# Remove known false-positive forced objects.
for rel,obj in [('drivers/mfd/Makefile','da903x.o'),('arch/arm/mach-omap2/Makefile','pm-debug.o')]:
    p=K/rel
    if p.exists():
        t=rd(p); lines=t.splitlines(); n=[x for x in lines if not(obj in x and 'HWT101 exact link provider' in x)]
        if n!=lines: wr(p,'\n'.join(n)+'\n')

# Correct charging notifier owner.
# The S10 base does not contain bq_bci_battery.c. Import the exact Huawei K3V2 donor file if missing.
bci=K/'drivers/power/bq_bci_battery.c'
donor_bci=R/'drivers/power/bq_bci_battery.c'
if not bci.exists():
    if not donor_bci.exists():
        raise RuntimeError('exact Huawei donor bq_bci_battery.c not found')
    bci.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(donor_bci, bci)
    print('IMPORTED', bci.relative_to(K))

t=rd(bci)
if 'BLOCKING_NOTIFIER_HEAD(notifier_list);' not in t:
    pos=t.find('#define WINDOW_LEN')
    if pos<0: raise RuntimeError('WINDOW_LEN marker not found in bq_bci_battery.c')
    t=t[:pos]+'BLOCKING_NOTIFIER_HEAD(notifier_list);\n\n'+t[pos:]
    wr(bci,t)

pmk=K/'drivers/power/Makefile'; t=rd(pmk)
# Avoid duplicate inclusion. If bq_bci_battery.o is already referenced under any CONFIG, keep it.
if 'bq_bci_battery.o' not in t:
    t+='\nobj-y += bq_bci_battery.o  # HWT101 OEM charging notifier provider\n'
    wr(pmk,t)

# Exact Huawei IPPS API.
dst=K/'arch/arm/mach-k3v2/ipps-core.c'; src=R/'arch/arm/mach-k3v2/ipps-core.c'; t=rd(dst)
if not re.search(r'(?m)^int\s+ipps_update_power_capacity\s*\(',t):
    t+='\n\n/* HWT101 exact Huawei K3V2 API */\n'+fn_extract(rd(src),'ipps_update_power_capacity')+'\n'; wr(dst,t)

# Exact Huawei recovery API; also transfer its simple backing variable if absent.
dst=K/'arch/arm/mach-k3v2/common.c'; src=R/'arch/arm/mach-k3v2/common.c'; t=rd(dst); s=rd(src)
if not re.search(r'(?m)^unsigned\s+int\s+get_boot_into_recovery_flag\s*\(',t):
    fn=fn_extract(s,'get_boot_into_recovery_flag'); prefix=''
    for ident in ('boot_into_recovery_flag','recovery_flag'):
        if ident in fn and ident not in t:
            m=re.search(r'(?m)^(?:static\s+)?(?:unsigned\s+int|int|u32)\s+'+re.escape(ident)+r'\s*(?:=\s*[^;\n]+)?\s*;',s)
            if m: prefix+=m.group(0)+'\n'
    t+='\n\n/* HWT101 exact Huawei K3V2 recovery API */\n'+prefix+fn+'\n'; wr(dst,t)

# Correct K3V2 wake timer variable type/provider (never OMAP).
wake_src=R/'arch/arm/mach-k3v2/k3v2_wakeup_timer.c'
s=rd(wake_src)
vm=re.search(r'(?m)^(?!\s*extern\b)(?:static\s+)?(?:unsigned\s+int|u32)\s+wakeup_timer_seconds\s*(?:=\s*[^;\n]+)?\s*;',s)
if not vm: raise RuntimeError('exact K3V2 wakeup_timer_seconds not found')

# FSA880-safe HIUSB compatibility provider. Do not enable CONFIG_SUPPORT_MICRO_USB_PORT.
compat=K/'arch/arm/mach-k3v2/hwt101_oem_compat.c'
compat.write_text('''/* HWT101 K3V2 compatibility for OEM charging glue. */
#include <linux/kernel.h>
#include <linux/types.h>
#include <linux/notifier.h>
#include <linux/usb/hiusb_android.h>

%s

static ATOMIC_NOTIFIER_HEAD(hwt101_charger_type_notifier_head);
static int hwt101_charger_type = CHARGER_REMOVED;

int get_charger_name(void)
{
    return hwt101_charger_type;
}

int hiusb_charger_registe_notifier(struct notifier_block *nb)
{
    return atomic_notifier_chain_register(&hwt101_charger_type_notifier_head, nb);
}

int hiusb_charger_unregiste_notifier(struct notifier_block *nb)
{
    return atomic_notifier_chain_unregister(&hwt101_charger_type_notifier_head, nb);
}
''' % vm.group(0))
print('PATCHED', compat.relative_to(K))
mk=K/'arch/arm/mach-k3v2/Makefile'; t=rd(mk)
if 'hwt101_oem_compat.o' not in t:
    t+='\nobj-y += hwt101_oem_compat.o  # HWT101 final OEM glue\n'; wr(mk,t)

Path('HWT101-FINAL-LINK-PATCH.txt').write_text('''HWT101 V3.22 final-link repair\nnotifier_list: exact donor bq_bci_battery.c imported when absent\nwakeup_timer_seconds: K3V2 provider type, no OMAP\nipps_update_power_capacity: exact donor implementation\nget_boot_into_recovery_flag: exact donor implementation\nHIUSB APIs: FSA880-safe provider, micro-USB board option remains disabled\n''')
print(Path('HWT101-FINAL-LINK-PATCH.txt').read_text())
