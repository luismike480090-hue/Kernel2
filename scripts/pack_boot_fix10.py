#!/usr/bin/env python3
# Repack an HWT101 boot image preserving FIX10 header, ramdisk and 16MiB partition image size.
from pathlib import Path
import struct,sys,hashlib
if len(sys.argv)!=4:
    print("usage: pack_boot_fix10.py FIX10_BOOT.img NEW_zImage OUT.img"); raise SystemExit(2)
base=bytearray(Path(sys.argv[1]).read_bytes())
z=Path(sys.argv[2]).read_bytes()
if base[:8]!=b"ANDROID!": raise SystemExit("bad FIX10 boot")
ks,ka,rs,ra,ss,sa,tags,ps,ds,unused=struct.unpack_from("<10I",base,8)
koff=ps
roff=((koff+ks+ps-1)//ps)*ps
oldrd=bytes(base[roff:roff+rs])
newroff=((koff+len(z)+ps-1)//ps)*ps
out=bytearray(len(base))
out[:ps]=base[:ps]
struct.pack_into("<I",out,8,len(z))
out[koff:koff+len(z)]=z
out[newroff:newroff+rs]=oldrd
Path(sys.argv[3]).write_bytes(out)
print("kernel",len(z),"ramdisk",rs,"page",ps,"output",len(out))
print("sha256",hashlib.sha256(out).hexdigest())
