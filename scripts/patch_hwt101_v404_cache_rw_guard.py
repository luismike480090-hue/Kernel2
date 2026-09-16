#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch_hwt101_v404_cache_rw_guard.py <kernel-root>')
K=Path(sys.argv[1])
p=K/'drivers/mtd/nand/hinand_hwt101.c'
s=p.read_text()

# CACHE is 256 MiB at physical NAND offset 1738 MiB.
# NAND page size = 8192 bytes.
# first page = 1738*MiB/8192 = 0x36500
# last  page = (1994*MiB/8192)-1 = 0x3e4ff
helper='''\n#define HWT_CACHE_FIRST_PAGE 0x36500U\n#define HWT_CACHE_LAST_PAGE  0x3e4ffU\n\nstatic u32 hwt_seqin_page(struct hwt_hinand *h)\n{\n    /* SEQIN uses 2 column cycles followed by 3 row/page cycles. */\n    return ((h->addr[0] >> 16) & 0xffffU) | ((h->addr[1] & 0xffU) << 16);\n}\n\nstatic u32 hwt_erase_page(struct hwt_hinand *h)\n{\n    /* ERASE1/ERASE2 use row/page cycles only. */\n    return h->addr[0] & 0x00ffffffU;\n}\n\nstatic int hwt_cache_page_allowed(u32 page)\n{\n    return page >= HWT_CACHE_FIRST_PAGE && page <= HWT_CACHE_LAST_PAGE;\n}\n'''
anchor='static inline u32 nfc_read(struct hwt_hinand *h, unsigned int reg)'
if anchor not in s:
    raise SystemExit('nfc_read anchor missing')
if 'HWT_CACHE_FIRST_PAGE' not in s:
    s=s.replace(anchor,helper+'\n'+anchor,1)

old_prog='''static void hwt_pageprog(struct hwt_hinand *h) {\n    printk(KERN_ERR "HWT101_V401_RO_GUARD: BLOCK PAGEPROG\\n");\n    h->addr_cycle=0;\n}'''
new_prog='''static void hwt_pageprog(struct hwt_hinand *h)\n{\n    u32 page = hwt_seqin_page(h);\n    if (!hwt_cache_page_allowed(page)) {\n        printk(KERN_ERR "HWT101_V404_CACHE_GUARD: BLOCK PAGEPROG page=0x%x\\n", page);\n        h->addr_cycle=0;\n        return;\n    }\n    printk(KERN_DEBUG "HWT101_V404_CACHE_GUARD: ALLOW PAGEPROG page=0x%x\\n", page);\n    hwt_clear_int(h);\n    nfc_write(h,0x200,NFC_INTEN);\n    nfc_write(h,0x3f,NFC_DMA_CFG);\n    nfc_write(h,0x4c7,NFC_CON);\n    nfc_write(h,(u32)h->dma_handle,NFC_DMA_ADDR);\n    nfc_write(h,(u32)h->dma_handle+0x2000,NFC_DMA_ADDR2);\n    nfc_write(h,0x01c00000,NFC_DMA_LEN2);\n    hwt_set_addr(h);\n    nfc_write(h,0x1080,NFC_CMD);\n    nfc_write(h,0x23,NFC_DMA_CTRL);\n    hwt_wait_int(h);\n    h->addr_cycle=0;\n}'''
if old_prog not in s:
    raise SystemExit('V4.01 PAGEPROG guard anchor missing')
s=s.replace(old_prog,new_prog,1)

old_erase='''case NAND_CMD_ERASE2:\n        printk(KERN_ERR "HWT101_V401_RO_GUARD: BLOCK ERASE2\\n");\n        h->addr_cycle=0;\n        break;'''
new_erase='''case NAND_CMD_ERASE2: {\n        u32 page = hwt_erase_page(h);\n        if (!hwt_cache_page_allowed(page)) {\n            printk(KERN_ERR "HWT101_V404_CACHE_GUARD: BLOCK ERASE2 page=0x%x\\n", page);\n            h->addr_cycle=0;\n            break;\n        }\n        printk(KERN_DEBUG "HWT101_V404_CACHE_GUARD: ALLOW ERASE2 page=0x%x\\n", page);\n        hwt_clear_int(h);\n        nfc_write(h,1,NFC_INTEN);\n        nfc_write(h,0xc7,NFC_CON);\n        nfc_write(h,3,NFC_DMA_CFG);\n        nfc_write(h,h->addr[0],NFC_ADDRL);\n        nfc_write(h,h->addr_cycle>4?h->addr[1]:0,NFC_ADDRH);\n        nfc_write(h,0xd060,NFC_CMD);\n        nfc_write(h,(h->addr_cycle<<9)|0x6d,NFC_OP);\n        hwt_wait_int(h);\n        break;\n    }'''
if old_erase not in s:
    raise SystemExit('V4.01 ERASE2 guard anchor missing')
s=s.replace(old_erase,new_erase,1)

old_master='''h->mtd.flags &= ~MTD_WRITEABLE;\n printk(KERN_INFO "HWT101_V401_RO_GUARD: MTD_WRITEABLE cleared\\n");'''
new_master='''h->mtd.flags |= MTD_WRITEABLE;\n printk(KERN_INFO "HWT101_V404_CACHE_GUARD: master MTD writable; physical writes restricted to CACHE\\n");'''
if old_master not in s:
    raise SystemExit('V4.01 MTD read-only anchor missing')
s=s.replace(old_master,new_master,1)

old_parse='''nr_parts=parse_mtd_partitions(&h->mtd,part_probes,&parts,0);hwt_diag_nr_parts=nr_parts;hwt_diag_stage=70;ret=nr_parts>0?mtd_device_register(&h->mtd,parts,nr_parts):mtd_device_register(&h->mtd,NULL,0);'''
new_parse='''nr_parts=parse_mtd_partitions(&h->mtd,part_probes,&parts,0);hwt_diag_nr_parts=nr_parts;hwt_diag_stage=70;\n if (nr_parts > 0) {\n  int pi;\n  for (pi=0; pi<nr_parts; pi++) {\n   if (!parts[pi].name || strcmp(parts[pi].name,"cache"))\n    parts[pi].mask_flags |= MTD_WRITEABLE;\n   else\n    parts[pi].mask_flags &= ~MTD_WRITEABLE;\n  }\n }\n ret=nr_parts>0?mtd_device_register(&h->mtd,parts,nr_parts):mtd_device_register(&h->mtd,NULL,0);'''
if old_parse not in s:
    raise SystemExit('partition registration anchor missing')
s=s.replace(old_parse,new_parse,1)

checks=[
 ('cache first page','HWT_CACHE_FIRST_PAGE 0x36500U' in s),
 ('cache last page','HWT_CACHE_LAST_PAGE  0x3e4ffU' in s),
 ('pageprog restored','nfc_write(h,0x1080,NFC_CMD)' in s),
 ('pageprog dma','nfc_write(h,0x23,NFC_DMA_CTRL)' in s),
 ('erase restored','nfc_write(h,0xd060,NFC_CMD)' in s),
 ('program guard','BLOCK PAGEPROG page=0x%x' in s),
 ('erase guard','BLOCK ERASE2 page=0x%x' in s),
 ('partition ro masks','parts[pi].mask_flags |= MTD_WRITEABLE' in s),
 ('cache exception','strcmp(parts[pi].name,"cache")' in s),
 ('OEM OOB','.offset = 2, .length = 30' in s),
 ('readstart','nfc_write(h,0x21,NFC_DMA_CTRL)' in s),
]
failed=[n for n,ok in checks if not ok]
if failed:
    raise SystemExit('V404 gate failed: '+', '.join(failed))
p.write_text(s)
print('V404_CACHE_RW_GUARD=PASS')
print('CACHE_FIRST_PAGE=0x36500')
print('CACHE_LAST_PAGE=0x3e4ff')
print('PAGEPROG=OEM_SEQUENCE_CACHE_ONLY')
print('ERASE2=OEM_SEQUENCE_CACHE_ONLY')
print('NON_CACHE_PARTITIONS=MTD_READONLY')
print('PHYSICAL_NON_CACHE_WRITES=BLOCKED')
