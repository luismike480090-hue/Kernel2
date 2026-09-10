#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch_hwt101_v366_hinand_map_swap.py <kernel-root>')

K = Path(sys.argv[1])
p = K / 'drivers/mtd/nand/hinand_hwt101.c'
s = p.read_text()

# K3V2 platform.h semantics:
#   REG_BASE_NAND      0xFD100000 -> NAND data/aperture
#   REG_BASE_NANDC_CFG 0xFD200000 -> NAND controller registers
# Keep the OEM-observed resource ranges exactly as reconstructed, but map
# r1 as controller regs and r0 as the data window.
old = ('h->regs=ioremap_nocache(r0->start,resource_size(r0));'
       'h->aux=ioremap_nocache(r1->start,resource_size(r1));'
       'hwt_diag_map0=!!h->regs;hwt_diag_map1=!!h->aux;')
new = ('h->regs=ioremap_nocache(r1->start,resource_size(r1));'
       'h->aux=ioremap_nocache(r0->start,resource_size(r0));'
       'hwt_diag_map0=!!h->regs;hwt_diag_map1=!!h->aux;')
if old not in s:
    raise SystemExit('V3.66 ioremap anchor missing')
s = s.replace(old, new, 1)

# Give this hardware run its own diagnostic signature.
if 'HWT101_V364A_HINAND_DIAG' not in s:
    raise SystemExit('V3.66 diagnostic signature anchor missing')
s = s.replace('HWT101_V364A_HINAND_DIAG', 'HWT101_V366_HINAND_DIAG', 1)

# Capture the first four bytes returned by READID.  For the OEM Micron NAND
# we expect byte0=0x2c and byte1=0x88 (READID32 low bytes 0x....882c).
anchor = 'static u32 hwt_diag_ints;\n'
if anchor not in s:
    raise SystemExit('V3.66 diag variable anchor missing')
s = s.replace(anchor, anchor + 'static u32 hwt_diag_readid32;\n', 1)

old = '"NFC_CON=0x%08x\\nNFC_STATUS=0x%08x\\nNFC_INTEN=0x%08x\\nNFC_INTS=0x%08x\\n",'
new = '"NFC_CON=0x%08x\\nNFC_STATUS=0x%08x\\nNFC_INTEN=0x%08x\\nNFC_INTS=0x%08x\\nREADID32=0x%08x\\n",'
if old not in s:
    raise SystemExit('V3.66 diag format anchor missing')
s = s.replace(old, new, 1)

old = 'hwt_diag_con, hwt_diag_status, hwt_diag_inten, hwt_diag_ints);'
new = 'hwt_diag_con, hwt_diag_status, hwt_diag_inten, hwt_diag_ints, hwt_diag_readid32);'
if old not in s:
    raise SystemExit('V3.66 diag args anchor missing')
s = s.replace(old, new, 1)

old = 'memcpy(h->dma_buf,(void __force const *)h->aux,16); h->page_offset=0; break;'
new = 'memcpy(h->dma_buf,(void __force const *)h->aux,16); memcpy(&hwt_diag_readid32,h->dma_buf,4); h->page_offset=0; break;'
if old not in s:
    raise SystemExit('V3.66 READID capture anchor missing')
s = s.replace(old, new, 1)

# Hard gates. Resource addresses/ranges themselves must not change.
for required in (
    '#define HWT_NFC_BASE       0xfd100000',
    '#define HWT_NFC_END        0xfd1007ff',
    '#define HWT_NFC_AUX_BASE   0xfd200000',
    '#define HWT_NFC_AUX_END    0xfd2000af',
    'h->regs=ioremap_nocache(r1->start,resource_size(r1));',
    'h->aux=ioremap_nocache(r0->start,resource_size(r0));',
    'HWT101_V366_HINAND_DIAG',
    'READID32=0x%08x',
    'memcpy(&hwt_diag_readid32,h->dma_buf,4);',
    '.coherent_dma_mask=0xffffffffULL,',
):
    if required not in s:
        raise SystemExit('V3.66 gate failed: ' + required)

p.write_text(s)
print('V366_HINAND_MAPPING=PASS')
print('NAND_DATA_PHYS=0xFD100000')
print('NANDC_REGS_PHYS=0xFD200000')
print('CONTROLLER_MAP=r1')
print('DATA_MAP=r0')
print('DMA_MASK_FIX=PRESERVED')
print('READID_DIAG=ENABLED')
print('MEMORY_LAYOUT=UNCHANGED_FROM_V363')
