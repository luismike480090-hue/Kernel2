#!/usr/bin/env python3
from pathlib import Path
import re, sys, shutil

if len(sys.argv) != 3:
    print("usage: resolve_hiusb_providers.py <kernel> <donor>")
    sys.exit(2)

K=Path(sys.argv[1]).resolve()
D=Path(sys.argv[2]).resolve()

SYMS=[
    "hiusb_charger_registe_notifier",
    "hiusb_charger_unregiste_notifier",
    "get_charger_name",
]

def definition(path, sym):
    try: t=path.read_text(errors="ignore")
    except: return False
    # Global function definition only; reject declarations and static defs.
    rx=re.compile(r'(?ms)^([A-Za-z_][^;\n{}]*?\b'+re.escape(sym)+r'\s*\([^;{}]*?\))\s*\{')
    for m in rx.finditer(t):
        sig=m.group(1)
        if re.search(r'(^|\s)static\s', sig):
            continue
        return True
    return False

def providers(root, sym):
    out=[]
    for p in root.rglob("*.c"):
        if "/.git/" in str(p): continue
        if definition(p,sym): out.append(p)
    return out

def force_object(src):
    mk=src.parent/"Makefile"
    obj=src.stem+".o"
    if not mk.exists():
        mk.write_text("")
    txt=mk.read_text(errors="ignore")
    # If object is already unconditionally built, nothing to do.
    if re.search(r'(?m)^\s*obj-y\s*\+?=.*\b'+re.escape(obj)+r'\b',txt):
        return
    with mk.open("a") as f:
        f.write("\n# HWT101 V3.18 exact HIUSB link provider\nobj-y += "+obj+"\n")

report=[]
for sym in SYMS:
    kp=providers(K,sym)
    if kp:
        report.append(f"{sym}: already in S10 -> {kp[0].relative_to(K)}")
        force_object(kp[0])
        continue

    dp=providers(D,sym)
    if not dp:
        report.append(f"{sym}: NO GLOBAL DONOR DEFINITION")
        continue

    # Prefer USB/charger source.
    dp.sort(key=lambda p:(0 if ("usb" in str(p).lower() or "charger" in str(p).lower()) else 1,
                          len(str(p))))
    donor=dp[0]
    rel=donor.relative_to(D)
    dst=K/rel
    if dst.exists():
        # Never overwrite S10. A same-path source without the symbol is a
        # semantic collision and must be diagnosed rather than replaced.
        report.append(f"{sym}: COLLISION {rel}; S10 source exists but lacks definition")
        continue

    dst.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(donor,dst)
    force_object(dst)
    report.append(f"{sym}: imported exact donor TU -> {rel}")

Path("HIUSB-PROVIDER-REPORT.txt").write_text("\n".join(report)+"\n")
print("\n".join(report))

missing=[x for x in report if "NO GLOBAL" in x or "COLLISION" in x]
if missing:
    print("V3.18: unresolved exact HIUSB provider(s); refusing guessed stubs.")
    sys.exit(95)
