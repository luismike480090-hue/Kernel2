#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch_hwt101_v401_readonly_guard.py <kernel-root>')
K=Path(sys.argv[1])
p=K/'drivers/mtd/nand/hinand_hwt101.c'
s=p.read_text()

# V4.01 first-boot safety guard. Physical NAND writes are blocked at the
# lowest reconstructed controller layer while READID/STATUS/RESET/READSTART
# remain intact. This is diagnostic-only and must not be used as Android RW.
old_prog='''static void hwt_pageprog(struct hwt_hinand *h) { hwt_clear_int(h); nfc_write(h,0x200,NFC_INTEN); nfc_write(h,0x3f,NFC_DMA_CFG); nfc_write(h,0x4c7,NFC_CON); nfc_write(h,(u32)h->dma_handle,NFC_DMA_ADDR); nfc_write(h,(u32)h->dma_handle+0x2000,NFC_DMA_ADDR2); nfc_write(h,0x01c00000,NFC_DMA_LEN2); hwt_set_addr(h); nfc_write(h,0x1080,NFC_CMD); nfc_write(h,0x23,NFC_DMA_CTRL); if(hwt_wait_int(h)) hwt_wait_status(h); h->addr_cycle=0; }'''
new_prog='''static void hwt_pageprog(struct hwt_hinand *h) {\n    printk(KERN_ERR "HWT101_V401_RO_GUARD: BLOCK PAGEPROG\\n");\n    h->addr_cycle=0;\n}'''
if old_prog not in s:
    raise SystemExit('PAGEPROG implementation anchor not found')
s=s.replace(old_prog,new_prog,1)

old_erase='''case NAND_CMD_ERASE2: hwt_clear_int(h); nfc_write(h,1,NFC_INTEN); nfc_write(h,0xc7,NFC_CON); nfc_write(h,3,NFC_DMA_CFG); nfc_write(h,h->addr[0],NFC_ADDRL); nfc_write(h,h->addr_cycle>4?h->addr[1]:0,NFC_ADDRH); nfc_write(h,0xd060,NFC_CMD); nfc_write(h,(h->addr_cycle<<9)|0x6d,NFC_OP); if(hwt_wait_int(h)) hwt_wait_status(h); break;'''
new_erase='''case NAND_CMD_ERASE2:\n        printk(KERN_ERR "HWT101_V401_RO_GUARD: BLOCK ERASE2\\n");\n        h->addr_cycle=0;\n        break;'''
if old_erase not in s:
    raise SystemExit('ERASE2 implementation anchor not found')
s=s.replace(old_erase,new_erase,1)

# Disable MTD writeability after nand_scan but before registration. This is an
# upper-layer belt-and-suspenders guard in addition to the command-layer block.
old_scan='''ret=nand_scan(&h->mtd,1);if(ret){ret=-ENXIO;goto err_irq;}\n nr_parts=parse_mtd_partitions'''
new_scan='''ret=nand_scan(&h->mtd,1);if(ret){ret=-ENXIO;goto err_irq;}\n h->mtd.flags &= ~MTD_WRITEABLE;\n printk(KERN_INFO "HWT101_V401_RO_GUARD: MTD_WRITEABLE cleared\\n");\n nr_parts=parse_mtd_partitions'''
if old_scan not in s:
    raise SystemExit('nand_scan registration anchor not found')
s=s.replace(old_scan,new_scan,1)

# Static gates: no controller-side physical program/erase command constants may
# remain in executable write paths. READSTART constants remain intentionally.
checks=[
 ('pageprog guard','BLOCK PAGEPROG' in s),
 ('erase guard','BLOCK ERASE2' in s),
 ('mtd ro flag','h->mtd.flags &= ~MTD_WRITEABLE;' in s),
 ('page program command removed','nfc_write(h,0x1080,NFC_CMD)' not in s),
 ('program dma removed','nfc_write(h,0x23,NFC_DMA_CTRL)' not in s),
 ('erase command removed','nfc_write(h,0xd060,NFC_CMD)' not in s),
 ('readstart preserved','nfc_write(h,HWT_DMA_SIZE,NFC_CMD)' in s),
 ('read dma preserved','nfc_write(h,0x21,NFC_DMA_CTRL)' in s),
 ('oem oob layout preserved','.offset = 2, .length = 30' in s),
 ('no system scan','hwt_capture_system_raw' not in s and 'HWT_RAW_SCAN_PAGES' not in s),
]
failed=[n for n,ok in checks if not ok]
if failed:
    raise SystemExit('V401 gate failed: '+', '.join(failed))
p.write_text(s)
print('V401_READONLY_GUARD=PASS')
print('PHYSICAL_PAGEPROG=BLOCKED')
print('PHYSICAL_ERASE2=BLOCKED')
print('MTD_WRITEABLE=CLEARED')
print('READSTART=PRESERVED')
print('OEM_OOB_LAYOUT=PRESERVED')
