#!/usr/bin/env python3
import os, re, sys, shutil
from pathlib import Path

if len(sys.argv) < 3:
    print("usage: import_link_providers.py <kernel> <reference>")
    sys.exit(2)

K = Path(sys.argv[1]).resolve()
R = Path(sys.argv[2]).resolve()

FUNCTION_SYMBOLS = [
    "get_battery_id",
    "ipps_update_power_capacity",
    "get_boot_into_recovery_flag",
    "is_bq27510_battery_exist",
    "is_bq27510_battery_full",
    "bq27510_battery_temperature",
    "bq27510_battery_voltage",
    "bq27510_battery_capacity",
    "bq27510_battery_current",
    "bq27510_get_gasgauge_normal_capacity",
    "bq27510_get_gasgauge_param_temperature",
    "nct203_temp_report",
    "hiusb_charger_registe_notifier",
    "hiusb_charger_unregiste_notifier",
    "get_charger_name",
]
VARIABLE_SYMBOLS = [
    "g_battery_measure_by_bq27510_device",
    "notifier_list",
    "wakeup_timer_seconds",
]

# V3.46 performance-only correction:
# Read every C file exactly once, then reuse the text for every symbol lookup.
# Provider scoring, precedence, collision rules and copied files are unchanged.
def cached_c_files(root):
    out=[]
    for p in root.rglob("*.c"):
        if "/.git/" in str(p):
            continue
        try:
            out.append((p,p.read_text(errors="ignore")))
        except Exception:
            pass
    return out

FILES = cached_c_files(R)
print("V3.46 cached donor C files:", len(FILES))

def find_function_provider(sym):
    pat = re.compile(r'(?m)^[^\n;]*\b' + re.escape(sym) +
                     r'\s*\([^;{}]*\)\s*\{', re.S)
    candidates=[]
    for p,t in FILES:
        if sym not in t:
            continue
        m=pat.search(t)
        if m:
            line=m.group(0)
            if re.search(r'(^|\s)static\s', line):
                continue
            candidates.append(p)
    return candidates

def find_variable_provider(sym):
    init_pat = re.compile(r'(?m)^(?!\s*extern\b)(?!\s*#)[^\n;]*\b' +
                          re.escape(sym) + r'\b\s*(?:=|;)')
    candidates=[]
    for p,t in FILES:
        if sym not in t:
            continue
        for m in init_pat.finditer(t):
            line=m.group(0)
            if "extern " in line or re.search(r'(^|\s)static\s', line):
                continue
            candidates.append(p)
            break
    return candidates

def score(path, sym):
    s=str(path).lower(); v=0
    if "drivers/power/" in s: v+=50
    if "drivers/usb/" in s: v+=40
    if "drivers/hwmon/" in s: v+=35
    if "arch/arm/mach-k3v2/" in s: v+=30
    if "bq27510" in s and "bq27510" in sym.lower(): v+=100
    if "nct203" in s and "nct203" in sym.lower(): v+=100
    if "hiusb" in s and ("hiusb" in sym.lower() or "charger_name" in sym.lower()): v+=100
    return v

providers={}; missing=[]
for sym in FUNCTION_SYMBOLS:
    cands=find_function_provider(sym)
    if not cands:
        missing.append(sym); continue
    cands.sort(key=lambda p:(-score(p,sym),len(str(p))))
    providers[sym]=cands[0]
for sym in VARIABLE_SYMBOLS:
    cands=find_variable_provider(sym)
    if not cands:
        missing.append(sym); continue
    cands.sort(key=lambda p:(-score(p,sym),len(str(p))))
    providers[sym]=cands[0]

print("===== EXACT LINK PROVIDERS FOUND =====")
for sym,p in providers.items():
    print(f"{sym}: {p.relative_to(R)}")
if missing:
    print("===== STILL MISSING =====")
    for sym in missing: print(sym)

KFILES = cached_c_files(K)
print("V3.46 cached S10 C files:", len(KFILES))

def find_function_provider_in(files,sym):
    pat=re.compile(r'(?m)^[^\n;]*\b'+re.escape(sym)+r'\s*\([^;{}]*\)\s*\{',re.S)
    out=[]
    for p,t in files:
        if sym not in t: continue
        m=pat.search(t)
        if m:
            if re.search(r'(^|\s)static\s',m.group(0)): continue
            out.append(p)
    return out

def find_variable_provider_in(files,sym):
    init_pat=re.compile(r'(?m)^(?!\s*extern\b)(?!\s*#)[^\n;]*\b'+re.escape(sym)+r'\b\s*(?:=|;)')
    out=[]
    for p,t in files:
        if sym not in t: continue
        for m in init_pat.finditer(t):
            line=m.group(0)
            if "extern " not in line and not re.search(r'(^|\s)static\s',line):
                out.append(p); break
    return out

def force_object_for_file(dst_c):
    rel=dst_c.relative_to(K); d=dst_c.parent; mk=d/"Makefile"; obj=dst_c.stem+".o"
    if not mk.exists(): mk.write_text("")
    txt=mk.read_text(errors="ignore"); lines=txt.splitlines(); found=False; changed=False; new_lines=[]
    for line in lines:
        if re.search(r'\b'+re.escape(obj)+r'\b',line):
            found=True
            if line.lstrip().startswith("obj-$(") and "+=" in line:
                new_lines.append(f"obj-y += {obj}  # HWT101 exact link provider"); changed=True
            else: new_lines.append(line)
        else: new_lines.append(line)
    if not found:
        new_lines.append(f"obj-y += {obj}  # HWT101 exact link provider"); changed=True
    if changed: mk.write_text("\n".join(new_lines)+"\n")
    print(f"FORCED OBJECT: {rel}")

resolved={}; conflicts=[]; copied=[]
for sym in FUNCTION_SYMBOLS+VARIABLE_SYMBOLS:
    kc=find_function_provider_in(KFILES,sym) if sym in FUNCTION_SYMBOLS else find_variable_provider_in(KFILES,sym)
    if kc:
        kc.sort(key=lambda p:(len(str(p)),str(p)))
        kp=kc[0]; force_object_for_file(kp); resolved[sym]=("S10",kp.relative_to(K)); continue
    dp=providers.get(sym)
    if dp is None: continue
    rel=dp.relative_to(R); dst=K/rel
    if dst.exists():
        force_object_for_file(dst); resolved[sym]=("S10-SAME-PATH-FORCED",rel)
        print(f"SAME-PATH PROVIDER: {sym}: preserved S10 {rel} and forced {dst.stem}.o")
        continue
    dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(dp,dst); force_object_for_file(dst)
    copied.append(dst); resolved[sym]=("DONOR",rel); print(f"IMPORTED NEW SOURCE: {rel}")

include_re=re.compile(r'^\s*#\s*include\s*<([^>]+)>',re.M)
for src in copied:
    t=src.read_text(errors="ignore"); rel=src.relative_to(K); donor_src=R/rel
    if not donor_src.is_file(): continue
    for inc in include_re.findall(t):
        if not inc.startswith("linux/"): continue
        rs=R/"include"/inc; kd=K/"include"/inc
        if rs.is_file() and not kd.exists():
            kd.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(rs,kd); print(f"IMPORTED MISSING HEADER ONLY: include/{inc}")
        elif rs.is_file() and kd.exists():
            print(f"PRESERVED S10 HEADER: include/{inc}")

report=K.parent/"LINK-PROVIDER-IMPORT.txt"
with report.open("w") as f:
    for sym in FUNCTION_SYMBOLS+VARIABLE_SYMBOLS:
        status=resolved.get(sym)
        if status: f.write(f"{sym}: {status[0]}:{status[1]}\n")
        elif sym in missing: f.write(f"{sym}: NOT FOUND\n")
        else:
            p=providers.get(sym); f.write(f"{sym}: DONOR:{p.relative_to(R) if p else 'NOT FOUND'}\n")

if missing:
    print("ERROR: one or more exact provider definitions are still missing.")
    print("See LINK-PROVIDER-IMPORT.txt")
    sys.exit(87)
if conflicts:
    print("===== SAFE SOURCE COLLISIONS =====")
    for sym,rel in conflicts: print(f"{sym}: {rel}")
    print("These donor files were NOT copied over S10.")
    print("See LINK-PROVIDER-IMPORT.txt")
    sys.exit(88)
print("All current unresolved symbols are provided without overwriting S10 sources/headers.")
