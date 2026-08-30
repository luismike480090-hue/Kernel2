#!/usr/bin/env python3
import os, re, sys, shutil
from pathlib import Path

if len(sys.argv) < 3:
    print("usage: import_link_providers.py <kernel> <reference>")
    sys.exit(2)

K = Path(sys.argv[1]).resolve()
R = Path(sys.argv[2]).resolve()

# Exact unresolved symbols from the current HWT101 link failure.
FUNCTION_SYMBOLS = [
    "get_battery_id",
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

def all_c_files():
    for p in R.rglob("*.c"):
        if "/.git/" not in str(p):
            yield p

FILES = list(all_c_files())

def find_function_provider(sym):
    # Function definition, allowing line breaks between ")" and "{".
    pat = re.compile(r'(?m)^[^\n;]*\b' + re.escape(sym) +
                     r'\s*\([^;{}]*\)\s*\{', re.S)
    candidates = []
    for p in FILES:
        try:
            t = p.read_text(errors="ignore")
        except Exception:
            continue
        if pat.search(t):
            candidates.append(p)
    return candidates

def find_variable_provider(sym):
    # Global non-extern definition. Prefer initialized/global declarations.
    init_pat = re.compile(r'(?m)^(?!\s*extern\b)(?!\s*#)[^\n;]*\b' +
                          re.escape(sym) + r'\b\s*(?:=|;)')
    candidates = []
    for p in FILES:
        try:
            t = p.read_text(errors="ignore")
        except Exception:
            continue
        for m in init_pat.finditer(t):
            line = m.group(0)
            if "extern " in line:
                continue
            # Skip obvious local declarations by preferring column-0 / static/global-looking lines.
            candidates.append(p)
            break
    return candidates

def score(path, sym):
    s = str(path).lower()
    v = 0
    if "drivers/power/" in s: v += 50
    if "drivers/usb/" in s: v += 40
    if "drivers/hwmon/" in s: v += 35
    if "arch/arm/mach-k3v2/" in s: v += 30
    if "bq27510" in s and "bq27510" in sym.lower(): v += 100
    if "nct203" in s and "nct203" in sym.lower(): v += 100
    if "hiusb" in s and ("hiusb" in sym.lower() or "charger_name" in sym.lower()): v += 100
    return v

providers = {}
missing = []

for sym in FUNCTION_SYMBOLS:
    cands = find_function_provider(sym)
    if not cands:
        missing.append(sym)
        continue
    cands.sort(key=lambda p: (-score(p, sym), len(str(p))))
    providers[sym] = cands[0]

for sym in VARIABLE_SYMBOLS:
    cands = find_variable_provider(sym)
    if not cands:
        missing.append(sym)
        continue
    cands.sort(key=lambda p: (-score(p, sym), len(str(p))))
    providers[sym] = cands[0]

print("===== EXACT LINK PROVIDERS FOUND =====")
for sym, p in providers.items():
    print(f"{sym}: {p.relative_to(R)}")
if missing:
    print("===== STILL MISSING =====")
    for sym in missing:
        print(sym)

# Unique exact source providers.
uniq = []
seen = set()
for p in providers.values():
    rp = str(p.relative_to(R))
    if rp not in seen:
        seen.add(rp)
        uniq.append(p)

def force_object(rel):
    dst_c = K / rel
    d = dst_c.parent
    mk = d / "Makefile"
    obj = dst_c.stem + ".o"
    if not mk.exists():
        mk.write_text("")
    txt = mk.read_text(errors="ignore")

    # If object is controlled by CONFIG_*, replace ONLY its simple obj-* line
    # by obj-y so the exact provider is guaranteed to be linked for this build.
    lines = txt.splitlines()
    changed = False
    found = False
    new_lines = []
    for line in lines:
        if re.search(r'\b' + re.escape(obj) + r'\b', line):
            found = True
            if line.lstrip().startswith("obj-$(") and "+=" in line:
                new_lines.append(f"obj-y += {obj}  # HWT101 exact link provider")
                changed = True
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"obj-y += {obj}  # HWT101 exact link provider")
        changed = True
    if changed:
        mk.write_text("\n".join(new_lines) + "\n")

for src in uniq:
    rel = src.relative_to(R)
    dst = K / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    force_object(rel)
    print(f"IMPORTED+FORCED: {rel}")

# Copy exact donor headers referenced by these providers when they live under
# include/linux and exist in the donor. This is deliberately narrow.
include_re = re.compile(r'^\s*#\s*include\s*<([^>]+)>', re.M)
for src in uniq:
    t = src.read_text(errors="ignore")
    for inc in include_re.findall(t):
        if not inc.startswith("linux/"):
            continue
        rs = R / "include" / inc
        if rs.is_file():
            kd = K / "include" / inc
            kd.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(rs, kd)

report = K.parent / "LINK-PROVIDER-IMPORT.txt"
with report.open("w") as f:
    for sym in FUNCTION_SYMBOLS + VARIABLE_SYMBOLS:
        p = providers.get(sym)
        f.write(f"{sym}: {p.relative_to(R) if p else 'NOT FOUND'}\n")

if missing:
    print("ERROR: one or more exact provider definitions are still missing.")
    print("See LINK-PROVIDER-IMPORT.txt")
    sys.exit(87)

print("All current unresolved symbols have exact donor providers.")
