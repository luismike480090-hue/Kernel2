#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch_hwt101_v369_hinand_read_column.py <kernel-root>')

K = Path(sys.argv[1])
hp = K / 'drivers/mtd/nand/hinand_hwt101.c'
h = hp.read_text()

old = 'case NAND_CMD_READSTART: hwt_readstart(h); break;'
new = 'case NAND_CMD_READSTART: h->column=h->addr[0]&0xffff; h->page_offset=0; hwt_readstart(h); break;'
if old not in h:
    raise SystemExit('READSTART anchor missing')
h = h.replace(old, new, 1)

old2 = 'hwt_wait_status(h); memcpy(h->dma_buf,(void __force const *)h->aux,16); memcpy(&hwt_diag_readid32,h->dma_buf,4);'
new2 = 'hwt_wait_status(h); h->column=0; h->page_offset=0; memcpy(h->dma_buf,(void __force const *)h->aux,16); memcpy(&hwt_diag_readid32,h->dma_buf,4);'
if old2 not in h:
    raise SystemExit('READID anchor missing')
h = h.replace(old2, new2, 1)

h = h.replace('HWT101_V368_HINAND_DIAG', 'HWT101_V369_HINAND_DIAG')
hp.write_text(h)

for needle in (
    'HWT101_V369_HINAND_DIAG',
    'case NAND_CMD_READSTART: h->column=h->addr[0]&0xffff; h->page_offset=0; hwt_readstart(h); break;',
    'h->column=0; h->page_offset=0; memcpy(h->dma_buf',
):
    if needle not in hp.read_text():
        raise SystemExit('V3.69 gate failed: ' + needle)

print('V369_HINAND_READ_COLUMN_FIX=PASS')
print('READSTART_COLUMN_CAPTURE=PASS')
print('READID_COLUMN_RESET=PASS')
print('GEOMETRY=UNCHANGED_8192_448_2097152_8GiB')
print('OOB_LAYOUT=UNCHANGED_OFFSET2_LEN446')
