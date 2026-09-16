#!/usr/bin/env python3
from pathlib import Path
import re, sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch_hwt101_v400_oem_hinand_yaffs2.py <kernel-root>')
K = Path(sys.argv[1])
hp = K/'drivers/mtd/nand/hinand_hwt101.c'
ids = K/'drivers/mtd/nand/nand_ids.c'
base = K/'drivers/mtd/nand/nand_base.c'
cmd = K/'drivers/mtd/cmdlinepart.c'

# 1) Replace V3.68 guessed geometry/OOB with exact FIX10 nand_ecclayout.
h = hp.read_text()
start = h.find('/* HWT101 V3.68: exact geometry observed in the functional OEM kernel.')
anchor = 'static inline u32 nfc_read(struct hwt_hinand *h, unsigned int reg)'
end = h.find(anchor)
if start < 0 or end < 0 or end <= start:
    raise SystemExit('V3.68 geometry/OOB block not found')

eccpos = ', '.join(str(x) for x in range(32, 80))
oem = f'''/* HWT101 V4.00: FIX10/OEM nand_ecclayout recovered byte-for-byte\n * from kernel address 0xc07e4fb0. Linux NAND ECC mode remains NONE because\n * the HiSilicon NFC performs ECC transparently (NFC_CON=0x4c7).\n * YAFFS2 tags are out-of-band; byte 0 is the bad-block marker, byte 1\n * reserved, bytes 2..31 are the only OEM-advertised free OOB bytes.\n */\nstatic struct nand_ecclayout hwt_hinand_oob_oem = {{\n    .eccbytes = 48,\n    .eccpos = {{ {eccpos} }},\n    .oobfree = {{\n        {{ .offset = 2, .length = 30 }},\n    }},\n}};\n\n'''
h = h[:start] + oem + h[end:]

old_cb = ('h->chip.read_byte=hinand_read_byte;h->chip.read_word=hinand_read_word;'
          'h->chip.read_buf=hinand_read_buf;h->chip.write_buf=hinand_write_buf;'
          'h->chip.init_size=hwt_hinand_init_size;h->chip.ecc.mode=NAND_ECC_NONE;'
          'h->chip.ecc.layout=&hwt_hinand_oob_448;')
new_cb = ('h->chip.read_byte=hinand_read_byte;h->chip.read_word=hinand_read_word;'
          'h->chip.read_buf=hinand_read_buf;h->chip.write_buf=hinand_write_buf;'
          'h->chip.ecc.mode=NAND_ECC_NONE;h->chip.ecc.layout=&hwt_hinand_oob_oem;')
if old_cb not in h:
    raise SystemExit('V3.68 probe callback sequence not found')
h = h.replace(old_cb, new_cb, 1)

# V3.50 already restored the OEM pre-ident options 0x501 exactly.
oem_opts = 'h->chip.options|=(NAND_NO_AUTOINCR|NAND_NO_READRDY|NAND_BROKEN_XD);'
if oem_opts not in h:
    raise SystemExit('OEM chip options 0x501 missing before V4 patch')

h = h.replace('OOBFREE_LENGTH=446', 'OOBFREE_LENGTH=30')
h = h.replace('HWT101_V369_HINAND_DIAG', 'HWT101_V400_HINAND_DIAG')
hp.write_text(h)

# 2) Exact FIX10 NAND ID entry recovered from OEM raw kernel table.
s = ids.read_text()
pat = re.compile(r'\{"NAND 8GiB 3,3V 8-bit",\s*0x88,\s*0,\s*8192,\s*0,\s*LP_OPTIONS\},')
rep = '{"NAND 8GiB 3,3V 8-bit",\t0x88, 8192, 8192, 0x200000, LP_OPTIONS},'
s, n = pat.subn(rep, s, count=1)
if n != 1:
    raise SystemExit('V3.67 Micron 0x88 ID entry not found')
ids.write_text(s)

# 3) Exact OEM 448-byte OOB for the fixed-page Micron 0x2c:0x88 path.
s = base.read_text()
old = '\t\tmtd->oobsize = mtd->writesize / 32;\n'
new = '''\t\t/* HWT101/FIX10 OEM parity: MT29F64G08CBAAA is 8192+448. */\n\t\tif (*maf_id == NAND_MFR_MICRON && *dev_id == 0x88 &&\n\t\t    mtd->writesize == 8192)\n\t\t\tmtd->oobsize = 448;\n\t\telse\n\t\t\tmtd->oobsize = mtd->writesize / 32;\n'''
if old not in s:
    raise SystemExit('fixed-page oobsize anchor not found')
s = s.replace(old, new, 1)
base.write_text(s)

# 4) Preserve memparse() 64-bit values through the ARM32 cmdline parser.
s = cmd.read_text()
changes = [
    ('#define SIZE_REMAINING UINT_MAX', '#define SIZE_REMAINING (~0ULL)'),
    ('#define OFFSET_CONTINUOUS UINT_MAX', '#define OFFSET_CONTINUOUS (~0ULL)'),
    ('\tunsigned long size;\n\tunsigned long offset = OFFSET_CONTINUOUS;',
     '\tunsigned long long size;\n\tunsigned long long offset = OFFSET_CONTINUOUS;'),
    ('partition size too small (%lx)', 'partition size too small (%llx)'),
    ('\tunsigned long offset;\n\tint i;\n\tstruct cmdline_mtd_partition *part;',
     '\tunsigned long long offset;\n\tint i;\n\tstruct cmdline_mtd_partition *part;'),
]
for a,b in changes:
    if a not in s:
        raise SystemExit('cmdlinepart anchor missing: '+repr(a))
    s = s.replace(a,b,1)
cmd.write_text(s)

# Hard gates.
h = hp.read_text(); sids=ids.read_text(); sb=base.read_text(); sc=cmd.read_text()
checks = [
    ('OEM diag marker', 'HWT101_V400_HINAND_DIAG' in h),
    ('OEM pre-ident options 0x501', oem_opts in h),
    ('OEM eccbytes', '.eccbytes = 48' in h),
    ('OEM eccpos start', '.eccpos = { 32, 33, 34' in h),
    ('OEM eccpos end', '77, 78, 79 }' in h),
    ('OEM oobfree', '.offset = 2, .length = 30' in h),
    ('ECC none', 'h->chip.ecc.mode=NAND_ECC_NONE' in h),
    ('OEM layout assigned', 'h->chip.ecc.layout=&hwt_hinand_oob_oem' in h),
    ('no init_size callback', 'hwt_hinand_init_size' not in h and 'chip.init_size=' not in h),
    ('no guessed 446 free', 'length = 446' not in h and 'OOBFREE_LENGTH=446' not in h),
    ('no V370 system scan', 'hwt_capture_system_raw' not in h and 'HWT_RAW_SCAN_PAGES' not in h),
    ('OEM ID fixed geometry', '0x88, 8192, 8192, 0x200000, LP_OPTIONS' in sids),
    ('OEM OOB core', 'mtd->oobsize = 448;' in sb),
    ('64-bit partition size', 'unsigned long long size;' in sc),
    ('64-bit partition offset', 'unsigned long long offset = OFFSET_CONTINUOUS;' in sc),
    ('64-bit parser offset', 'unsigned long long offset;' in sc),
]
failed=[name for name,ok in checks if not ok]
if failed:
    raise SystemExit('V400 gate failed: '+', '.join(failed))

print('V400_OEM_HINAND_YAFFS2_PARITY=PASS')
print('BASE=EXACT_V369_WITH_V350_OEM_OPTIONS_V349_CLOCK_IRQ_V366_MAP')
print('MICRON=2c:88 MT29F64G08CBAAA')
print('NAND=8GiB PAGE=8192 OOB=448 ERASE=2097152')
print('OEM_NAND_ID_ENTRY=8192_8192MiB_2MiB_0x11d')
print('ECC_MODE=NAND_ECC_NONE_CONTROLLER_INTERNAL')
print('OEM_ECCLAYOUT=ECCBYTES48_ECCPOS32_79_OOBFREE2_30')
print('YAFFS2=OUT_OF_BAND_TAGS')
print('CMDLINEPART_64BIT=YES')
print('V370_AUTO_SYSTEM_READ=ABSENT')
