#!/usr/bin/env python3
from pathlib import Path
import re, sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch_hwt101_v352_persistdiag.py <kernel-root>')
K = Path(sys.argv[1])

# HiSilicon's pmem allocator always leaves more than 1 MiB of top padding
# below 0x40000000. Use only 64 KiB at 0x3ff00000 for a warm-reset journal.
BASE = 0x3ff00000
SIZE = 0x00010000

hdr = K / 'include/linux/hwt101_bootdiag.h'
hdr.write_text(r'''#ifndef _LINUX_HWT101_BOOTDIAG_H
#define _LINUX_HWT101_BOOTDIAG_H
#include <linux/types.h>
#define HWTDIAG_BASE 0x3ff00000UL
#define HWTDIAG_SIZE 0x00010000UL
#define HWT_EVT_BOOT_READY      0x00000001
#define HWT_EVT_INIT_ENTER      0x00001001
#define HWT_EVT_INIT_EXIT       0x00001002
#define HWT_EVT_PANIC           0x0000dead
#define HWT_EVT_HINAND_BASE     0x00002000
void hwt101_diag_event(u32 type, u32 a, u32 b);
#endif
''')

cfile = K / 'arch/arm/mach-k3v2/hwt101_bootdiag.c'
cfile.write_text(r'''/* HWT101 V3.52 persistent warm-reset boot checkpoint journal. */
#include <linux/init.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/io.h>
#include <linux/spinlock.h>
#include <linux/hwt101_bootdiag.h>

#define HWT_MAGIC       0x32445748U /* "HWD2" LE */
#define HWT_VERSION     0x00035201U
#define HWT_HEADER_SIZE 0x40
#define HWT_REC_SIZE    16
#define HWT_CAPACITY    ((HWTDIAG_SIZE-HWT_HEADER_SIZE)/HWT_REC_SIZE)

static void __iomem *hwt_base;
static u32 hwt_seq;
static u32 hwt_index;
static DEFINE_SPINLOCK(hwt_lock);

static inline void hwt_wr(u32 off, u32 v)
{
    writel(v, hwt_base + off);
}

void hwt101_diag_event(u32 type, u32 a, u32 b)
{
    unsigned long flags;
    u32 off;
    if (!hwt_base)
        return;
    spin_lock_irqsave(&hwt_lock, flags);
    if (hwt_index >= HWT_CAPACITY)
        hwt_index = 0;
    off = HWT_HEADER_SIZE + hwt_index * HWT_REC_SIZE;
    hwt_wr(off + 0, ++hwt_seq);
    hwt_wr(off + 4, type);
    hwt_wr(off + 8, a);
    hwt_wr(off + 12, b);
    hwt_index++;
    hwt_wr(0x08, hwt_index);
    hwt_wr(0x0c, hwt_seq);
    wmb();
    spin_unlock_irqrestore(&hwt_lock, flags);
}
EXPORT_SYMBOL(hwt101_diag_event);

static int __init hwt101_bootdiag_init(void)
{
    hwt_base = ioremap_nocache(HWTDIAG_BASE, HWTDIAG_SIZE);
    if (!hwt_base)
        return -ENOMEM;

    hwt_seq = 0;
    hwt_index = 0;
    hwt_wr(0x00, HWT_MAGIC);
    hwt_wr(0x04, HWT_VERSION);
    hwt_wr(0x08, 0);
    hwt_wr(0x0c, 0);
    hwt_wr(0x10, HWTDIAG_BASE);
    hwt_wr(0x14, HWTDIAG_SIZE);
    hwt_wr(0x18, HWT_CAPACITY);
    hwt_wr(0x1c, 0x54455354U); /* TEST */
    wmb();
    hwt101_diag_event(HWT_EVT_BOOT_READY, 0, 0);
    printk(KERN_EMERG "HWTDIAG2: persistent journal ready phys=0x%08lx size=0x%lx\n",
           HWTDIAG_BASE, HWTDIAG_SIZE);
    return 0;
}
arch_initcall(hwt101_bootdiag_init);
''')

mk = K / 'arch/arm/mach-k3v2/Makefile'
m = mk.read_text()
line = 'obj-y += hwt101_bootdiag.o\n'
if line not in m:
    m += '\n# HWT101 V3.52 warm-reset boot diagnostics\n' + line
mk.write_text(m)

# Capture every initcall after the journal becomes available.
main = K / 'init/main.c'
s = main.read_text()
if '#include <linux/hwt101_bootdiag.h>' not in s:
    anchor = '#include <linux/kdb.h>\n'
    if anchor not in s:
        anchor = '#include <linux/init.h>\n'
    if anchor not in s:
        raise SystemExit('main.c include anchor missing')
    s = s.replace(anchor, anchor + '#include <linux/hwt101_bootdiag.h>\n', 1)

old = '''int __init_or_module do_one_initcall(initcall_t fn)\n{\n\tint count = preempt_count();\n\tint ret;\n\n\tif (initcall_debug)\n\t\tret = do_one_initcall_debug(fn);\n\telse\n\t\tret = fn();\n'''
new = '''int __init_or_module do_one_initcall(initcall_t fn)\n{\n\tint count = preempt_count();\n\tint ret;\n\n\thwt101_diag_event(HWT_EVT_INIT_ENTER, (u32)fn, 0);\n\tif (initcall_debug)\n\t\tret = do_one_initcall_debug(fn);\n\telse\n\t\tret = fn();\n\thwt101_diag_event(HWT_EVT_INIT_EXIT, (u32)fn, (u32)ret);\n'''
if old not in s:
    raise SystemExit('do_one_initcall anchor missing')
s = s.replace(old, new, 1)
if 'int initcall_debug;' not in s:
    raise SystemExit('initcall_debug anchor missing')
s = s.replace('int initcall_debug;', 'int initcall_debug = 1; /* HWT101 V3.52 */', 1)
main.write_text(s)

# Mark panic entry. Linux 3.0.8 uses: NORET_TYPE void panic(const char * fmt, ...)
panic = K / 'kernel/panic.c'
p = panic.read_text()
if '#include <linux/hwt101_bootdiag.h>' not in p:
    inc = '#include <linux/kernel.h>\n'
    if inc not in p:
        inc = '#include <linux/module.h>\n'
    if inc not in p:
        raise SystemExit('panic include anchor missing')
    p = p.replace(inc, inc + '#include <linux/hwt101_bootdiag.h>\n', 1)
pat = r'(NORET_TYPE\s+void\s+panic\s*\(\s*const\s+char\s*\*\s*fmt\s*,\s*\.\.\.\s*\)\s*\{)'
p, count = re.subn(pat, r'\1\n\thwt101_diag_event(HWT_EVT_PANIC, 0, 0);', p, count=1)
if count != 1:
    raise SystemExit('panic() Linux 3.0.8 anchor missing')
panic.write_text(p)

# HINAND checkpoints only. Controller logic/register values stay V3.50-identical.
nand = K / 'drivers/mtd/nand/hinand_hwt101.c'
n = nand.read_text()
if '#include <linux/hwt101_bootdiag.h>' not in n:
    inc = '#include <linux/module.h>\n'
    if inc not in n:
        raise SystemExit('HINAND include anchor missing')
    n = n.replace(inc, inc + '#include <linux/hwt101_bootdiag.h>\n', 1)

def once(old, new, label):
    global n
    if old not in n:
        raise SystemExit('HINAND diagnostic anchor missing: ' + label)
    n = n.replace(old, new, 1)

once('static int hinand_probe(struct platform_device*pdev){',
     'static int hinand_probe(struct platform_device*pdev){hwt101_diag_event(HWT_EVT_HINAND_BASE+1,0,0);', 'probe-enter')
once('r0=platform_get_resource(pdev,IORESOURCE_MEM,0);',
     'hwt101_diag_event(HWT_EVT_HINAND_BASE+2,0,0);r0=platform_get_resource(pdev,IORESOURCE_MEM,0);', 'resources')
once('h->regs=ioremap_nocache(r0->start,resource_size(r0));',
     'hwt101_diag_event(HWT_EVT_HINAND_BASE+3,(u32)h->irq,(u32)r0->start);h->regs=ioremap_nocache(r0->start,resource_size(r0));', 'ioremap')
once('h->dma_buf=dma_alloc_coherent(&pdev->dev,HWT_DMA_SIZE,&h->dma_handle,GFP_KERNEL);',
     'hwt101_diag_event(HWT_EVT_HINAND_BASE+4,(u32)h->regs,(u32)h->aux);h->dma_buf=dma_alloc_coherent(&pdev->dev,HWT_DMA_SIZE,&h->dma_handle,GFP_KERNEL);', 'dma')
once('hinand_init(&h->mtd);ret=request_irq',
     'hwt101_diag_event(HWT_EVT_HINAND_BASE+5,0,0);hinand_init(&h->mtd);hwt101_diag_event(HWT_EVT_HINAND_BASE+6,0,0);ret=request_irq', 'init')
once('ret=nand_scan(&h->mtd,1);if(ret)',
     'hwt101_diag_event(HWT_EVT_HINAND_BASE+7,(u32)h->irq,0);ret=nand_scan(&h->mtd,1);hwt101_diag_event(HWT_EVT_HINAND_BASE+8,(u32)ret,0);if(ret)', 'scan')
once('nr_parts=parse_mtd_partitions(&h->mtd,part_probes,&parts,0);',
     'hwt101_diag_event(HWT_EVT_HINAND_BASE+9,0,0);nr_parts=parse_mtd_partitions(&h->mtd,part_probes,&parts,0);', 'parts')
once('if(ret)goto err_nand;return 0;',
     'hwt101_diag_event(HWT_EVT_HINAND_BASE+10,(u32)ret,(u32)nr_parts);if(ret)goto err_nand;hwt101_diag_event(HWT_EVT_HINAND_BASE+11,0,0);return 0;', 'probe-pass')
once('case NAND_CMD_READID:',
     'case NAND_CMD_READID: hwt101_diag_event(HWT_EVT_HINAND_BASE+0x20,0,0);', 'readid')
once('case NAND_CMD_RESET:',
     'case NAND_CMD_RESET: hwt101_diag_event(HWT_EVT_HINAND_BASE+0x21,0,0);', 'reset')
once('printk(KERN_WARNING "lby mode=%x\\n", readb(h->aux));',
     'printk(KERN_WARNING "lby mode=%x\\n", readb(h->aux)); hwt101_diag_event(HWT_EVT_HINAND_BASE+0x22,(u32)readb(h->aux),0);', 'lby')
nand.write_text(n)

print('V3.52 persistent boot checkpoint journal installed')
print('PERSIST_BASE=0x%08x' % BASE)
print('PERSIST_END=0x%08x' % (BASE + SIZE - 1))
print('PERSIST_SIZE=0x%x' % SIZE)
print('INITCALL enter/exit + PANIC + HINAND stages enabled')
print('NAND logic/register programming unchanged from V3.50')
