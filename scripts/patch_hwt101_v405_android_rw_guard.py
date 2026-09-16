#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch_hwt101_v405_android_rw_guard.py <kernel-root>')
K=Path(sys.argv[1])
p=K/'drivers/mtd/nand/hinand_hwt101.c'
s=p.read_text()

# V4.05 is derived from V4.03/V4.01 after V4.04B passed physical CACHE
# PAGEPROG + ERASE2 + reboot persistence on real HWT101 hardware.
# Keep the proven controller sequence unchanged. Only expand the physical
# write window from CACHE to the contiguous Android storage region:
#   SYSTEM  714..1738 MiB   pages 0x16500..0x364ff
#   CACHE  1738..1994 MiB   pages 0x36500..0x3e4ff
#   CUST   1994..2506 MiB   pages 0x3e500..0x4e4ff
#   CUST2  2506..3018 MiB   pages 0x4e500..0x5e4ff
#   USERDATA 3018..8192 MiB pages 0x5e500..0xfffff
# Everything below SYSTEM remains physically blocked, protecting boot/nvme/
# nvme2/oeminfo/recovery/misc/xloader/efi/fastboot and unused lower gaps.

anchor='''static inline u32 nfc_read(struct hwt_hinand *h, unsigned int reg) { return readl(h->regs + reg); }'''
insert='''#define HWT_ANDROID_FIRST_PAGE 0x16500U\n#define HWT_ANDROID_LAST_PAGE  0xfffffU\n\nstatic u32 hwt_seqin_page(struct hwt_hinand *h)\n{\n    /* SEQIN uses 2 column cycles followed by 3 row/page cycles. */\n    return ((h->addr[0] >> 16) & 0xffffU) | ((h->addr[1] & 0xffU) << 16);\n}\n\nstatic u32 hwt_erase_page(struct hwt_hinand *h)\n{\n    /* ERASE1/ERASE2 use row/page cycles only. */\n    return h->addr[0] & 0x00ffffffU;\n}\n\nstatic int hwt_android_page_allowed(u32 page)\n{\n    return page >= HWT_ANDROID_FIRST_PAGE && page <= HWT_ANDROID_LAST_PAGE;\n}\n\n'''+anchor
if anchor not in s:
    raise SystemExit('V4.01 nfc_read anchor not found')
s=s.replace(anchor,insert,1)

old_prog='''static void hwt_pageprog(struct hwt_hinand *h) {\n    printk(KERN_ERR "HWT101_V401_RO_GUARD: BLOCK PAGEPROG\\n");\n    h->addr_cycle=0;\n}'''
new_prog='''static void hwt_pageprog(struct hwt_hinand *h)\n{\n    u32 page = hwt_seqin_page(h);\n    if (!hwt_android_page_allowed(page)) {\n        printk(KERN_ERR "HWT101_V405_ANDROID_GUARD: BLOCK PAGEPROG page=0x%x\\n", page);\n        h->addr_cycle=0;\n        return;\n    }\n    printk(KERN_DEBUG "HWT101_V405_ANDROID_GUARD: ALLOW PAGEPROG page=0x%x\\n", page);\n    hwt_clear_int(h);\n    nfc_write(h,0x200,NFC_INTEN);\n    nfc_write(h,0x3f,NFC_DMA_CFG);\n    nfc_write(h,0x4c7,NFC_CON);\n    nfc_write(h,(u32)h->dma_handle,NFC_DMA_ADDR);\n    nfc_write(h,(u32)h->dma_handle+0x2000,NFC_DMA_ADDR2);\n    nfc_write(h,0x01c00000,NFC_DMA_LEN2);\n    hwt_set_addr(h);\n    nfc_write(h,0x1080,NFC_CMD);\n    nfc_write(h,0x23,NFC_DMA_CTRL);\n    hwt_wait_int(h);\n    h->addr_cycle=0;\n}'''
if old_prog not in s:
    raise SystemExit('V4.01 blocked PAGEPROG anchor not found')
s=s.replace(old_prog,new_prog,1)

old_erase='''case NAND_CMD_ERASE2:\n        printk(KERN_ERR "HWT101_V401_RO_GUARD: BLOCK ERASE2\\n");\n        h->addr_cycle=0;\n        break;'''
new_erase='''case NAND_CMD_ERASE2: {\n        u32 page = hwt_erase_page(h);\n        if (!hwt_android_page_allowed(page)) {\n            printk(KERN_ERR "HWT101_V405_ANDROID_GUARD: BLOCK ERASE2 page=0x%x\\n", page);\n            h->addr_cycle=0;\n            break;\n        }\n        printk(KERN_DEBUG "HWT101_V405_ANDROID_GUARD: ALLOW ERASE2 page=0x%x\\n", page);\n        hwt_clear_int(h);\n        nfc_write(h,1,NFC_INTEN);\n        nfc_write(h,0xc7,NFC_CON);\n        nfc_write(h,3,NFC_DMA_CFG);\n        nfc_write(h,h->addr[0],NFC_ADDRL);\n        nfc_write(h,h->addr_cycle>4?h->addr[1]:0,NFC_ADDRH);\n        nfc_write(h,0xd060,NFC_CMD);\n        nfc_write(h,(h->addr_cycle<<9)|0x6d,NFC_OP);\n        hwt_wait_int(h);\n        break;\n    }'''
if old_erase not in s:
    raise SystemExit('V4.01 blocked ERASE2 anchor not found')
s=s.replace(old_erase,new_erase,1)

old_scan='''hwt_diag_stage=60;\n h->mtd.flags &= ~MTD_WRITEABLE;\n printk(KERN_INFO "HWT101_V401_RO_GUARD: MTD_WRITEABLE cleared\\n");\n nr_parts=parse_mtd_partitions(&h->mtd,part_probes,&parts,0);hwt_diag_nr_parts=nr_parts;hwt_diag_stage=70;'''
new_scan='''hwt_diag_stage=60;\n h->mtd.flags |= MTD_WRITEABLE;\n printk(KERN_INFO "HWT101_V405_ANDROID_GUARD: master writable; physical writes limited to Android region 0x16500..0xfffff\\n");\n nr_parts=parse_mtd_partitions(&h->mtd,part_probes,&parts,0);hwt_diag_nr_parts=nr_parts;hwt_diag_stage=70;\n if (nr_parts > 0) {\n  int pi;\n  for (pi=0; pi<nr_parts; pi++) {\n   const char *n=parts[pi].name;\n   int android_rw = n && (!strcmp(n,"system") || !strcmp(n,"cache") ||\n                         !strcmp(n,"cust") || !strcmp(n,"cust2") ||\n                         !strcmp(n,"userdata"));\n   if (android_rw)\n    parts[pi].mask_flags &= ~MTD_WRITEABLE;\n   else\n    parts[pi].mask_flags |= MTD_WRITEABLE;\n  }\n }'''
if old_scan not in s:
    raise SystemExit('V4.01 MTD read-only anchor not found')
s=s.replace(old_scan,new_scan,1)

checks=[
 ('android first page','HWT_ANDROID_FIRST_PAGE 0x16500U' in s),
 ('android last page','HWT_ANDROID_LAST_PAGE  0xfffffU' in s),
 ('physical guard','hwt_android_page_allowed' in s),
 ('page program restored','nfc_write(h,0x1080,NFC_CMD)' in s),
 ('program DMA restored','nfc_write(h,0x23,NFC_DMA_CTRL)' in s),
 ('erase restored','nfc_write(h,0xd060,NFC_CMD)' in s),
 ('system allowed','!strcmp(n,"system")' in s),
 ('cache allowed','!strcmp(n,"cache")' in s),
 ('cust allowed','!strcmp(n,"cust")' in s),
 ('cust2 allowed','!strcmp(n,"cust2")' in s),
 ('userdata allowed','!strcmp(n,"userdata")' in s),
 ('V401 guard removed','HWT101_V401_RO_GUARD' not in s),
 ('readstart preserved','nfc_write(h,HWT_DMA_SIZE,NFC_CMD)' in s),
 ('OEM NFC ECC preserved','nfc_write(h,0x4c7,NFC_CON)' in s),
 ('OEM OOB preserved','.offset = 2, .length = 30' in s),
 ('no raw system scanner','hwt_capture_system_raw' not in s and 'HWT_RAW_SCAN_PAGES' not in s),
]
failed=[n for n,ok in checks if not ok]
if failed:
    raise SystemExit('V405 gate failed: '+', '.join(failed))
p.write_text(s)
print('V405_ANDROID_RW_GUARD=PASS')
print('PHYSICAL_ALLOWED_PAGES=0x16500..0xfffff')
print('PHYSICAL_BLOCK_BELOW_SYSTEM=YES')
print('RW_PARTITIONS=system,cache,cust,cust2,userdata')
print('PROTECTED_PARTITIONS=fastboot,efi,xloader,misc,oeminfo,recovery,boot,nvme,nvme2')
print('PAGEPROG_SEQUENCE=V404B_PROVEN')
print('ERASE2_SEQUENCE=V404B_PROVEN')
print('YAFFS_OEM_TAGS=PRESERVED')
