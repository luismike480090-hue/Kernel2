#!/usr/bin/env python3
from pathlib import Path
import sys,re,hashlib
k=Path(sys.argv[1] if len(sys.argv)>1 else "kernel")
checks={
"SN65 source": k/"drivers/video/k3/sn65dsi83_hwt101.c",
"Toshiba": k/"drivers/video/k3/panel/mipi_toshiba_MDW70_V001.c",
"MIPI": k/"drivers/video/k3/mipi_dsi.c",
"K3 framebuffer": k/"drivers/video/k3/k3_fb.c",
"S5K5CAG": k/"drivers/media/video/hik3/capture/s5k5cag/s5k5cag.c",
}
bad=0
for n,p in checks.items():
    ok=p.exists()
    print(("OK  " if ok else "MISS"),n,p)
    bad |= not ok
cfg=(k/".config").read_text(errors="ignore") if (k/".config").exists() else ""
for x in ["CONFIG_SWAP=y","CONFIG_ZRAM=y","CONFIG_XVMALLOC=y","CONFIG_LZO_COMPRESS=y","CONFIG_LZO_DECOMPRESS=y"]:
    print(("OK  " if x in cfg else "MISS"),x)
    bad |= x not in cfg
# exact SN table fingerprint
p=k/"drivers/video/k3/sn65dsi83_oem_table.h"
if p.exists():
    t=p.read_text()
    print("SN65 table pairs:",len(re.findall(r'\{ 0x[0-9A-F]{2}, 0x[0-9A-F]{2} \}',t)))
sys.exit(1 if bad else 0)
