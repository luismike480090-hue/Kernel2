#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch_hwt101_v368_hinand_init_size_oob.py <kernel-root>')

K = Path(sys.argv[1])
hp = K / 'drivers/mtd/nand/hinand_hwt101.c'
h = hp.read_text()

# Add exact OEM geometry callback + explicit 448-byte OOB layout.
anchor = 'static inline u32 nfc_read(struct hwt_hinand *h, unsigned int reg)'
if anchor not in h:
    raise SystemExit('nfc_read anchor missing')

block = r'''
/* HWT101 V3.68: exact geometry observed in the functional OEM kernel.
 * Micron MT29F64G08CBAAA: 2c 88 04 4b 00 00 00 00
 * 8GiB, 8192-byte page, 448-byte OOB, 2MiB erase block, x8 bus.
 *
 * The old generic NAND 3.0.8 extended-ID decoder interprets 0x4b as
 * a 16-bit device and computes OOB/erase geometry incorrectly.  Supplying
 * init_size() makes nand_get_flash_type() use the board-specific geometry
 * exactly as the Huawei OEM path did.
 */
static struct nand_ecclayout hwt_hinand_oob_448 = {
    .eccbytes = 0,
    .oobfree = {
        { .offset = 2, .length = 446 },
    },
};

static int hwt_hinand_init_size(struct mtd_info *mtd,
                                struct nand_chip *chip, u8 *id_data)
{
    if (id_data[0] != NAND_MFR_MICRON || id_data[1] != 0x88) {
        printk(KERN_ERR "HWT368: unexpected NAND id %02x:%02x:%02x:%02x\n",
               id_data[0], id_data[1], id_data[2], id_data[3]);
        return 0;
    }

    mtd->writesize = 8192;
    mtd->oobsize = 448;
    mtd->erasesize = 2 * 1024 * 1024;
    chip->options &= ~NAND_BUSWIDTH_16;

    printk(KERN_INFO "HWT368: Micron 2c:88 geometry 8K+448 erase=2MiB x8\n");
    return 0; /* 8-bit bus */
}

'''
if 'HWT368: Micron 2c:88 geometry' not in h:
    h = h.replace(anchor, block + anchor, 1)

# Extend proc diagnostics with callback/layout evidence.
h = h.replace('static u64 hwt_diag_mtd_size;\n',
              'static u64 hwt_diag_mtd_size;\nstatic int hwt_diag_init_size_called;\nstatic u32 hwt_diag_layout_oobavail;\n', 1)

oldfmt = '"NFC_CON=0x%08x\\nNFC_STATUS=0x%08x\\nNFC_INTEN=0x%08x\\nNFC_INTS=0x%08x\\nREADID32=0x%08x\\nREADID_HI32=0x%08x\\nWRITESIZE=%u\\nOOBSIZE=%u\\nERASESIZE=%u\\nMTD_SIZE=%llu\\n",'
newfmt = '"NFC_CON=0x%08x\\nNFC_STATUS=0x%08x\\nNFC_INTEN=0x%08x\\nNFC_INTS=0x%08x\\nREADID32=0x%08x\\nREADID_HI32=0x%08x\\nWRITESIZE=%u\\nOOBSIZE=%u\\nERASESIZE=%u\\nMTD_SIZE=%llu\\nINIT_SIZE_CALLED=%d\\nOOBFREE_OFFSET=2\\nOOBFREE_LENGTH=446\\nOOBAVAIL=%u\\n",'
if oldfmt not in h:
    raise SystemExit('diag format anchor missing')
h = h.replace(oldfmt, newfmt, 1)

oldargs = 'hwt_diag_con, hwt_diag_status, hwt_diag_inten, hwt_diag_ints, hwt_diag_readid32, hwt_diag_readid_hi32, hwt_diag_writesize, hwt_diag_oobsize, hwt_diag_erasesize, (unsigned long long)hwt_diag_mtd_size);'
newargs = 'hwt_diag_con, hwt_diag_status, hwt_diag_inten, hwt_diag_ints, hwt_diag_readid32, hwt_diag_readid_hi32, hwt_diag_writesize, hwt_diag_oobsize, hwt_diag_erasesize, (unsigned long long)hwt_diag_mtd_size, hwt_diag_init_size_called, hwt_diag_layout_oobavail);'
if oldargs not in h:
    raise SystemExit('diag args anchor missing')
h = h.replace(oldargs, newargs, 1)

# Mark callback invocation.
marker = '    mtd->writesize = 8192;\n'
h = h.replace(marker, '    hwt_diag_init_size_called = 1;\n' + marker, 1)

# Install init_size and OOB layout before nand_scan().
old = 'h->chip.read_byte=hinand_read_byte;h->chip.read_word=hinand_read_word;h->chip.read_buf=hinand_read_buf;h->chip.write_buf=hinand_write_buf;h->chip.ecc.mode=NAND_ECC_NONE;'
new = 'h->chip.read_byte=hinand_read_byte;h->chip.read_word=hinand_read_word;h->chip.read_buf=hinand_read_buf;h->chip.write_buf=hinand_write_buf;h->chip.init_size=hwt_hinand_init_size;h->chip.ecc.mode=NAND_ECC_NONE;h->chip.ecc.layout=&hwt_hinand_oob_448;'
if old not in h:
    raise SystemExit('probe callback anchor missing')
h = h.replace(old, new, 1)

# Capture final oobavail after nand_scan_tail() succeeds.
oldscan = 'ret=nand_scan(&h->mtd,1);hwt_diag_nand_scan=ret;hwt_diag_writesize=h->mtd.writesize;hwt_diag_oobsize=h->mtd.oobsize;hwt_diag_erasesize=h->mtd.erasesize;hwt_diag_mtd_size=h->mtd.size;if(ret){hwt_diag_stage=-60;ret=-ENXIO;goto err_irq;}hwt_diag_stage=60;'
newscan = 'ret=nand_scan(&h->mtd,1);hwt_diag_nand_scan=ret;hwt_diag_writesize=h->mtd.writesize;hwt_diag_oobsize=h->mtd.oobsize;hwt_diag_erasesize=h->mtd.erasesize;hwt_diag_mtd_size=h->mtd.size;hwt_diag_layout_oobavail=h->mtd.oobavail;if(ret){hwt_diag_stage=-60;ret=-ENXIO;goto err_irq;}hwt_diag_stage=60;'
if oldscan not in h:
    raise SystemExit('nand_scan anchor missing')
h = h.replace(oldscan, newscan, 1)

h = h.replace('HWT101_V367_HINAND_DIAG', 'HWT101_V368_HINAND_DIAG')
hp.write_text(h)

checks = [
    'HWT101_V368_HINAND_DIAG',
    'hwt_hinand_init_size',
    'mtd->writesize = 8192;',
    'mtd->oobsize = 448;',
    'mtd->erasesize = 2 * 1024 * 1024;',
    'chip->options &= ~NAND_BUSWIDTH_16;',
    '.offset = 2, .length = 446',
    'h->chip.init_size=hwt_hinand_init_size',
    'h->chip.ecc.layout=&hwt_hinand_oob_448',
]
for needle in checks:
    if needle not in hp.read_text():
        raise SystemExit('V3.68 gate failed: ' + needle)

print('V368_HINAND_INIT_SIZE_OOB=PASS')
print('ID=2c:88:04:4b:00:00:00:00')
print('PAGE=8192')
print('OOB=448')
print('ERASE=2097152')
print('CHIPSIZE_FROM_NAND_ID_TABLE=8192MiB')
print('BUSWIDTH=8')
print('OOBFREE=2+446')
