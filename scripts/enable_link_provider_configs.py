#!/usr/bin/env python3
from pathlib import Path
import re, sys

if len(sys.argv) < 3:
    print("usage: enable_link_provider_configs.py <kernel> <reference>")
    sys.exit(2)

K=Path(sys.argv[1]).resolve()
R=Path(sys.argv[2]).resolve()
CONFIG=K/".config"

SYMS=[
 "notifier_list","wakeup_timer_seconds",
 "ipps_update_power_capacity","get_boot_into_recovery_flag",
 "hiusb_charger_registe_notifier","hiusb_charger_unregiste_notifier",
 "get_charger_name",
]

def files(root):
    return [p for p in root.rglob("*.c") if "/.git/" not in str(p)]

def global_function_hit(p,sym):
    try:t=p.read_text(errors="ignore")
    except:return None
    rx=re.compile(r'(?m)^([^\n;]*\b'+re.escape(sym)+r'\s*\([^;{}]*\)\s*)\{',re.S)
    for m in rx.finditer(t):
        sig=m.group(1)
        if re.search(r'(^|\s)static\s',sig): continue
        return m.start(),t
    return None

def global_variable_hit(p,sym):
    try:t=p.read_text(errors="ignore")
    except:return None
    rx=re.compile(r'(?m)^(?!\s*extern\b)([^\n;]*\b'+re.escape(sym)+r'\b\s*(?:=[^;]*)?;)')
    for m in rx.finditer(t):
        line=m.group(1)
        if re.search(r'(^|\s)static\s',line): continue
        # Avoid obvious function-local indented declarations.
        if len(line)-len(line.lstrip()) > 0: continue
        return m.start(),t
    return None

def score(p,sym):
    q=str(p).lower(); v=0
    if "drivers/power/" in q:v+=80
    if "drivers/usb/" in q:v+=70
    if "arch/arm/mach-k3v2/" in q:v+=60
    if "ipps" in q and "ipps" in sym:v+=150
    if "bq" in q and sym in ("notifier_list","wakeup_timer_seconds"):v+=80
    if "hiusb" in q and ("hiusb" in sym or sym=="get_charger_name"):v+=150
    return v

def choose(root,sym):
    hits=[]
    for p in files(root):
        h=global_function_hit(p,sym) or global_variable_hit(p,sym)
        if h:hits.append((score(p,sym),p,h))
    hits.sort(key=lambda x:(-x[0],len(str(x[1]))))
    return hits[0] if hits else None

def positive_guards(text,pos):
    # Track simple preprocessor nesting up to the definition.
    stack=[]
    for line in text[:pos].splitlines():
        st=line.strip()
        if st.startswith("#ifdef "):
            stack.append(("pos",[st.split(None,1)[1].strip()]))
        elif st.startswith("#ifndef "):
            stack.append(("neg",[st.split(None,1)[1].strip()]))
        elif st.startswith("#if "):
            expr=st[4:]
            poscfg=re.findall(r'(?:defined\s*\(\s*|defined\s+)(CONFIG_[A-Za-z0-9_]+)',expr)
            if not poscfg:
                # Also support "#if CONFIG_X"
                poscfg=re.findall(r'\b(CONFIG_[A-Za-z0-9_]+)\b',expr) if "!" not in expr else []
            stack.append(("pos",poscfg))
        elif st.startswith("#elif "):
            if stack: stack.pop()
            expr=st[6:]
            poscfg=re.findall(r'(?:defined\s*\(\s*|defined\s+)(CONFIG_[A-Za-z0-9_]+)',expr)
            stack.append(("pos",poscfg))
        elif st.startswith("#else"):
            if stack:
                kind,cfgs=stack.pop()
                stack.append(("neg" if kind=="pos" else "pos",cfgs))
        elif st.startswith("#endif"):
            if stack: stack.pop()
    out=[]
    for kind,cfgs in stack:
        if kind=="pos": out.extend(c for c in cfgs if c.startswith("CONFIG_"))
    return sorted(set(out))

def makefile_guard(src):
    mk=src.parent/"Makefile"
    if not mk.exists():return []
    obj=src.stem+".o"
    out=[]
    for line in mk.read_text(errors="ignore").splitlines():
        if obj in line:
            out += re.findall(r'obj-\$\((CONFIG_[A-Za-z0-9_]+)\)',line)
    return out

def set_y(name):
    txt=CONFIG.read_text(errors="ignore")
    rx1=re.compile(r'^'+re.escape(name)+r'=.*$',re.M)
    rx2=re.compile(r'^# '+re.escape(name)+r' is not set$',re.M)
    if rx1.search(txt):
        txt=rx1.sub(name+"=y",txt)
    elif rx2.search(txt):
        txt=rx2.sub(name+"=y",txt)
    else:
        txt += "\n"+name+"=y\n"
    CONFIG.write_text(txt)

report=[]
needed=set()
for sym in SYMS:
    h=choose(K,sym)
    origin="S10"
    if not h:
        h=choose(R,sym); origin="DONOR"
    if not h:
        report.append(f"{sym}: NO GLOBAL PROVIDER")
        continue
    _,p,(pos,text)=h
    guards=positive_guards(text,pos)
    # If same relative source exists in S10 use its Makefile gate.
    rel=p.relative_to(K if origin=="S10" else R)
    kp=K/rel
    guards += makefile_guard(kp if kp.exists() else p)
    guards=sorted(set(guards))
    report.append(f"{sym}: {origin}:{rel} guards={','.join(guards) if guards else 'none'}")
    needed.update(guards)

for c in sorted(needed):
    set_y(c)
    print("V3.16 CONFIG ENABLED:",c)

Path("LINK-PROVIDER-CONFIGS.txt").write_text("\n".join(report)+"\n")
print("\n".join(report))
