#!/usr/bin/env python3
from pathlib import Path
import re, sys, json

K = Path(sys.argv[1] if len(sys.argv)>1 else "kernel")
R = Path(sys.argv[2] if len(sys.argv)>2 else "huawei-k3-reference")
O = Path(sys.argv[3] if len(sys.argv)>3 else "oem_recovered")
OUT = Path("HWT101-MISSING-DRIVER-PARITY.txt")

specs = {
 "GOODIX": {
   "exact": ["goodix_ts_probe","goodix_ts_work_func"],
   "anchors": ["gtp_request_io_port","gtp_i2c_test","GTP I2C Address"],
   "roots": ["drivers/input/touchscreen"],
 },
 "FT5X0X": {
   "exact": ["ft5x0x_ts_probe","ft5x0x_ts_pen_irq_work"],
   "anchors": ["ft5x0x_i2c_Read","ft5x0x_ts_pen_irq_work","FT5X0X"],
   "roots": ["drivers/input/touchscreen"],
 },
 "GC0339": {
   "exact": ["gc0339_init","gc0339_power","gc0339_init_reg"],
   "anchors": ["k3_ispio_init_csi","k3_ispio_write_seq_ex","gc0339"],
   "roots": ["drivers/media/video/hik3/capture","drivers/media/video"],
 },
}

def cfiles(root, subroots):
    out=[]
    for sr in subroots:
        p=root/sr
        if p.exists():
            out += list(p.rglob("*.c"))
    return out

def score_file(p, exact, anchors):
    try: t=p.read_text(errors="ignore")
    except: return (0,[],[])
    e=[x for x in exact if x in t]
    a=[x for x in anchors if x in t]
    return (len(e)*100+len(a)*10,e,a)

lines=[]
lines.append("HWT101 MISSING DRIVER PARITY / V3.14")
lines.append("Policy: no generic driver is promoted to flashable without OEM/K3V2 parity.")
lines.append("")

for name,s in specs.items():
    lines.append(f"===== {name} =====")
    ranked=[]
    for label,root in [("S10",K),("HUAWEI_REF",R)]:
        for p in cfiles(root,s["roots"]):
            sc,e,a=score_file(p,s["exact"],s["anchors"])
            if sc:
                ranked.append((sc,label,p,e,a))
    ranked.sort(reverse=True,key=lambda x:x[0])
    if not ranked:
        lines.append("NO SOURCE CANDIDATE in S10/reference.")
    else:
        for sc,label,p,e,a in ranked[:10]:
            root=K if label=="S10" else R
            lines.append(f"{label} score={sc} {p.relative_to(root)} exact={e} anchors={a}")
    lines.append("")

# Verify exact OEM blobs needed for GC0339 reconstruction.
required = [
 O/"camera/gc0339_init_blob.bin",
 O/"camera/gc0339_isp_blob.bin",
 O/"camera/gc0339_framesize_blob.bin",
]
lines.append("===== GC0339 OEM DATA =====")
for p in required:
    lines.append(f"{p}: {'PRESENT '+str(p.stat().st_size)+' bytes' if p.exists() else 'MISSING'}")

# S5K5CAG must stay present as the K3 camera API template.
s5 = K/"drivers/media/video/hik3/capture/s5k5cag/s5k5cag.c"
lines.append("")
lines.append("===== S5K5CAG K3 TEMPLATE =====")
lines.append(f"{s5}: {'PRESENT' if s5.exists() else 'MISSING'}")

OUT.write_text("\n".join(lines)+"\n")
print(OUT.read_text())

# Hard fail only for missing OEM recovery data/template; external generic
# drivers are never silently accepted.
if any(not p.exists() for p in required) or not s5.exists():
    sys.exit(91)
