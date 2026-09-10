#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch_hwt101_v365_hinand_dma_mask.py <kernel-root>')

K = Path(sys.argv[1])
p = K / 'drivers/mtd/nand/hinand_hwt101.c'
s = p.read_text()

old = 'static void hinand_platdev_release(struct device*dev){}\nstatic struct platform_device hwt_hinand_device={.name="hisi_nand",.id=-1,.num_resources=ARRAY_SIZE(hwt_hinand_resources),.resource=hwt_hinand_resources,.dev={.release=hinand_platdev_release,},};'
new = '''static void hinand_platdev_release(struct device*dev){}
static u64 hwt_hinand_dma_mask = 0xffffffffULL;
static struct platform_device hwt_hinand_device={
 .name="hisi_nand",
 .id=-1,
 .num_resources=ARRAY_SIZE(hwt_hinand_resources),
 .resource=hwt_hinand_resources,
 .dev={
  .release=hinand_platdev_release,
  .dma_mask=&hwt_hinand_dma_mask,
  .coherent_dma_mask=0xffffffffULL,
 },
};'''

if old not in s:
    raise SystemExit('HiNAND platform_device anchor missing')
s = s.replace(old, new, 1)

# Hard gates: this is the only functional change in V3.65.
for required in (
    'static u64 hwt_hinand_dma_mask = 0xffffffffULL;',
    '.dma_mask=&hwt_hinand_dma_mask,',
    '.coherent_dma_mask=0xffffffffULL,',
    'dma_alloc_coherent(&pdev->dev,HWT_DMA_SIZE,&h->dma_handle,GFP_KERNEL)',
    'create_proc_read_entry("hwt_hinand_diag",0444',
):
    if required not in s:
        raise SystemExit('V3.65 DMA gate failed: ' + required)

p.write_text(s)
print('V365_HINAND_DMA_MASK=PASS')
print('DMA_MASK=0xffffffff')
print('COHERENT_DMA_MASK=0xffffffff')
print('MEMORY_LAYOUT=UNCHANGED_FROM_V364A_V363')
print('NAND_DIAG=PRESERVED')
