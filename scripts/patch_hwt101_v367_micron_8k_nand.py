#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch_hwt101_v367_micron_8k_nand.py <kernel-root>')

K = Path(sys.argv[1])
ids = K / 'drivers/mtd/nand/nand_ids.c'
base = K / 'drivers/mtd/nand/nand_base.c'
hp = K / 'drivers/mtd/nand/hinand_hwt101.c'

# Linux-MTD backport: Micron MT29F64G08CBAAA, ID 2c 88 04 4b a9 00 00.
s = ids.read_text()
anchor = '\t/* 64 Gigabit */\n'
entry = '\t{"NAND 8GiB 3,3V 8-bit",\t0x88, 0, 8192, 0, LP_OPTIONS},\n'
if entry not in s:
    if anchor not in s:
        raise SystemExit('nand_ids 64G anchor missing')
    s = s.replace(anchor, anchor + entry, 1)
ids.write_text(s)

s = base.read_text()
old = '''\t\t\t/* Calc oobsize */
\t\t\tmtd->oobsize = (8 << (extid & 0x01)) *
\t\t\t\t(mtd->writesize >> 9);
\t\t\textid >>= 2;
\t\t\t/* Calc blocksize. Blocksize is multiples of 64KiB */
\t\t\tmtd->erasesize = (64 * 1024) << (extid & 0x03);
\t\t\textid >>= 2;
\t\t\t/* Get buswidth information */
\t\t\tbusw = (extid & 0x01) ? NAND_BUSWIDTH_16 : 0;
'''
new = '''\t\t\t/* HWT101 V3.67: Linux-MTD Micron >=4KiB page heuristic.
\t\t\t * MT29F64G08CBAAA = 2c 88 04 4b a9 00 00,
\t\t\t * 8KiB page, 448B OOB, 2MiB erase block, x8 bus.
\t\t\t */
\t\t\tif (id_data[0] == NAND_MFR_MICRON && id_data[4] != 0x00
\t\t\t\t\t&& mtd->writesize >= 4096
\t\t\t\t\t&& id_data[5] == 0x00
\t\t\t\t\t&& id_data[6] == 0x00) {
\t\t\t\t/* OOB is 218B/224B per 4KiB pagesize */
\t\t\t\tmtd->oobsize = ((extid & 0x03) == 0x03 ? 218 :
\t\t\t\t\t\t224) << (mtd->writesize >> 13);
\t\t\t\textid >>= 3;
\t\t\t\t/* Blocksize is multiple of 64KiB */
\t\t\t\tmtd->erasesize = mtd->writesize <<
\t\t\t\t\t(extid & 0x03) << 6;
\t\t\t\tbusw = 0;
\t\t\t} else {
\t\t\t\t/* Calc oobsize */
\t\t\t\tmtd->oobsize = (8 << (extid & 0x01)) *
\t\t\t\t\t(mtd->writesize >> 9);
\t\t\t\textid >>= 2;
\t\t\t\t/* Calc blocksize. Blocksize is multiples of 64KiB */
\t\t\t\tmtd->erasesize = (64 * 1024) << (extid & 0x03);
\t\t\t\textid >>= 2;
\t\t\t\t/* Get buswidth information */
\t\t\t\tbusw = (extid & 0x01) ? NAND_BUSWIDTH_16 : 0;
\t\t\t}
'''
if 'HWT101 V3.67: Linux-MTD Micron >=4KiB page heuristic.' not in s:
    if old not in s:
        raise SystemExit('nand_base extid anchor missing')
    s = s.replace(old, new, 1)
base.write_text(s)

# Extend the existing V3.66 proc diagnostic with full ID and geometry.
h = hp.read_text()
h = h.replace('static u32 hwt_diag_readid32;\n',
              'static u32 hwt_diag_readid32;\nstatic u32 hwt_diag_readid_hi32;\nstatic u32 hwt_diag_writesize;\nstatic u32 hwt_diag_oobsize;\nstatic u32 hwt_diag_erasesize;\nstatic u64 hwt_diag_mtd_size;\n', 1)
h = h.replace('"NFC_CON=0x%08x\\nNFC_STATUS=0x%08x\\nNFC_INTEN=0x%08x\\nNFC_INTS=0x%08x\\nREADID32=0x%08x\\n",',
              '"NFC_CON=0x%08x\\nNFC_STATUS=0x%08x\\nNFC_INTEN=0x%08x\\nNFC_INTS=0x%08x\\nREADID32=0x%08x\\nREADID_HI32=0x%08x\\nWRITESIZE=%u\\nOOBSIZE=%u\\nERASESIZE=%u\\nMTD_SIZE=%llu\\n",', 1)
h = h.replace('hwt_diag_con, hwt_diag_status, hwt_diag_inten, hwt_diag_ints, hwt_diag_readid32);',
              'hwt_diag_con, hwt_diag_status, hwt_diag_inten, hwt_diag_ints, hwt_diag_readid32, hwt_diag_readid_hi32, hwt_diag_writesize, hwt_diag_oobsize, hwt_diag_erasesize, (unsigned long long)hwt_diag_mtd_size);', 1)
h = h.replace('memcpy(&hwt_diag_readid32,h->dma_buf,4); h->page_offset=0;',
              'memcpy(&hwt_diag_readid32,h->dma_buf,4); memcpy(&hwt_diag_readid_hi32,h->dma_buf+4,4); h->page_offset=0;', 1)
oldscan = 'ret=nand_scan(&h->mtd,1);hwt_diag_nand_scan=ret;if(ret){hwt_diag_stage=-60;ret=-ENXIO;goto err_irq;}hwt_diag_stage=60;'
newscan = 'ret=nand_scan(&h->mtd,1);hwt_diag_nand_scan=ret;hwt_diag_writesize=h->mtd.writesize;hwt_diag_oobsize=h->mtd.oobsize;hwt_diag_erasesize=h->mtd.erasesize;hwt_diag_mtd_size=h->mtd.size;if(ret){hwt_diag_stage=-60;ret=-ENXIO;goto err_irq;}hwt_diag_stage=60;'
if oldscan not in h:
    raise SystemExit('V3.66 nand_scan diagnostic anchor missing')
h = h.replace(oldscan, newscan, 1)
h = h.replace('HWT101_V366_HINAND_DIAG', 'HWT101_V367_HINAND_DIAG')
hp.write_text(h)

# Hard gates.
checks = [
    (ids, '0x88, 0, 8192, 0, LP_OPTIONS'),
    (base, 'HWT101 V3.67: Linux-MTD Micron >=4KiB page heuristic.'),
    (base, 'id_data[0] == NAND_MFR_MICRON'),
    (hp, 'HWT101_V367_HINAND_DIAG'),
    (hp, 'READID_HI32=0x%08x'),
    (hp, 'WRITESIZE=%u'),
    (hp, 'hwt_diag_mtd_size=h->mtd.size'),
]
for p, needle in checks:
    if needle not in p.read_text():
        raise SystemExit('V3.67 gate failed: ' + needle)

print('V367_MICRON_8K_NAND=PASS')
print('DEVICE=MT29F64G08CBAAA')
print('ID=2c:88:04:4b:a9:00:00')
print('NAND_SIZE=8GiB')
print('PAGE=8192')
print('OOB=448')
print('ERASEBLOCK=2097152')
print('SOURCE=Linux-MTD Micron >=4KiB support backport')
