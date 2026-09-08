#!/usr/bin/env python3
from pathlib import Path
import re, runpy, sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch_hwt101_hinand_fix10_v348.py <kernel-root>')

K = Path(sys.argv[1])

# Start from the existing HWT101 8K-page reconstruction, then replace only
# behavior we have now verified directly from the known-good FIX10 binary.
saved_argv = sys.argv[:]
try:
    sys.argv = ['scripts/add_hwt101_hinand_v340.py', str(K)]
    runpy.run_path('scripts/add_hwt101_hinand_v340.py', run_name='__main__')
finally:
    sys.argv = saved_argv

P = K / 'drivers/mtd/nand/hinand_hwt101.c'
s = P.read_text()

# OEM FIX10 absolute K3V2 clock/reset register addresses recovered from
# hinand_init @ c031d2a4. These are the exact virtual IO addresses touched by
# the running OEM kernel before NFC_CON/DMA/IRQ initialization.
needle = '#define NFC_DMA_LEN   0x80\n'
insert = '''#define NFC_DMA_LEN   0x80

/* FIX10 OEM K3V2 NAND clock/reset registers (absolute mapped IO VA). */
#define K3V2_NAND_EN_REG3       ((void __iomem *)0xfe2a2050)
#define K3V2_NAND_RST_REG3      ((void __iomem *)0xfe2a20a4)
#define K3V2_NAND_RSTDIS_REG3   ((void __iomem *)0xfe2a20a8)
#define K3V2_NAND_CFG0          ((void __iomem *)0xfe2a300c)
#define K3V2_NAND_CFG1          ((void __iomem *)0xfe2a3010)
#define K3V2_NAND_CFG2          ((void __iomem *)0xfe2a3014)
#define K3V2_NAND_CFG3          ((void __iomem *)0xfe2a3018)
#define K3V2_NAND_CFG4          ((void __iomem *)0xfe2a301c)
#define K3V2_NAND_CFG5          ((void __iomem *)0xfe2a3020)
#define K3V2_NAND_CFG6          ((void __iomem *)0xfe2a3024)
#define K3V2_NAND_CFG7          ((void __iomem *)0xfe2a3028)
#define K3V2_NAND_CFG8          ((void __iomem *)0xfe2a302c)
'''
if needle not in s:
    raise SystemExit('NFC register anchor not found')
s = s.replace(needle, insert, 1)

old = 'static int hwt_wait_status(struct hwt_hinand *h) { int n=1000000; while (!(nfc_read(h,NFC_STATUS)&1) && --n) cpu_relax(); return n?0:-ETIMEDOUT; }'
new = '''static int hwt_wait_status(struct hwt_hinand *h)
{
    int n = 0x2710;
    u32 status;
    do {
        status = nfc_read(h, NFC_STATUS);
        if (status & 1)
            return (int)status;
        cpu_relax();
    } while (--n);
    printk(KERN_ERR "hinand: wait status timeout\\n");
    return -1;
}'''
if old not in s:
    raise SystemExit('old wait_status implementation not found')
s = s.replace(old, new, 1)

old = 'static irqreturn_t hinand_irq(int irq, void *dev_id) { struct hwt_hinand *h=dev_id; u32 s=nfc_read(h,NFC_INTS); nfc_write(h,0,NFC_INTEN); nfc_write(h,s&0x7ff,NFC_INTCLR); complete(&h->done); return IRQ_HANDLED; }'
new = '''static irqreturn_t hinand_irq(int irq, void *dev_id)
{
    struct hwt_hinand *h = dev_id;
    u32 status = nfc_read(h, NFC_INTS);
    nfc_write(h, 0, NFC_INTEN);
    nfc_write(h, 0x7ff, NFC_INTCLR);
    /* FIX10 completes only for the two NAND interrupt causes it accepts. */
    if (status & 0x201)
        complete(&h->done);
    return IRQ_HANDLED;
}'''
if old not in s:
    raise SystemExit('old IRQ implementation not found')
s = s.replace(old, new, 1)

old = 'static int hwt_wait_int(struct hwt_hinand *h) { unsigned long t; reinit_completion(&h->done); t=wait_for_completion_timeout(&h->done,msecs_to_jiffies(1000)); return t?0:-ETIMEDOUT; }'
new = '''static int hwt_wait_int(struct hwt_hinand *h)
{
    unsigned long t;
    /* FIX10 waits 0x2710 ticks and does NOT reinitialize after starting DMA;
     * doing that here can lose an interrupt that arrives before the wait. */
    t = wait_for_completion_timeout(&h->done, 0x2710);
    if (t)
        return 0;
    printk(KERN_ERR "hinand: wait interrupt timeout\\n");
    return -ETIMEDOUT;
}'''
if old not in s:
    raise SystemExit('old wait_int implementation not found')
s = s.replace(old, new, 1)

old = 'void hinand_init(struct mtd_info*mtd){struct nand_chip*c=mtd->priv;struct hwt_hinand*h=c->priv;nfc_write(h,0x47,NFC_CON);nfc_write(h,0,NFC_PWIDTH);nfc_write(h,3,NFC_DMA_CFG);nfc_write(h,0,NFC_INTEN);nfc_write(h,0x7ff,NFC_INTCLR);} EXPORT_SYMBOL(hinand_init);'
new = '''void hinand_init(struct mtd_info *mtd)
{
    struct nand_chip *c = mtd->priv;
    struct hwt_hinand *h = c->priv;
    u32 v;

    /* Exact FIX10 sequence recovered from c031d2a4..c031d400. */
    v = readl(K3V2_NAND_EN_REG3);
    printk(KERN_INFO "EN_REG3 value 0x%x\\n", v);
    v |= 0x00080000;
    printk(KERN_INFO "EN_REG3 value 0x%x\\n", v);
    writel(v, K3V2_NAND_EN_REG3);

    v = readl(K3V2_NAND_RST_REG3);
    printk(KERN_INFO "RST_REG3 value 0x%x\\n", v);
    writel(0x00400000, K3V2_NAND_RST_REG3);
    writel(0x00400000, K3V2_NAND_RSTDIS_REG3);

    writel(0, K3V2_NAND_CFG0);
    writel(0, K3V2_NAND_CFG1);
    writel(0, K3V2_NAND_CFG2);
    writel(0, K3V2_NAND_CFG3);
    writel(0, K3V2_NAND_CFG4);
    writel(0, K3V2_NAND_CFG5);
    writel(0, K3V2_NAND_CFG6);
    writel(0, K3V2_NAND_CFG7);
    writel(0, K3V2_NAND_CFG8);
    mb();

    nfc_write(h, 0x47, NFC_CON);
    nfc_write(h, 0, NFC_PWIDTH);
    nfc_write(h, 3, NFC_DMA_CFG);
    nfc_write(h, 0, NFC_INTEN);
    nfc_write(h, 0x7ff, NFC_INTCLR);
}
EXPORT_SYMBOL(hinand_init);'''
if old not in s:
    raise SystemExit('old hinand_init implementation not found')
s = s.replace(old, new, 1)

# The old helper used reinit_completion(), unavailable in some 3.0 trees.
if 'reinit_completion' in s:
    raise SystemExit('reinit_completion unexpectedly survived')

P.write_text(s)

# Storage parity that FIX10 demonstrably has: NAND core + IDs + cmdline MTD + YAFFS.
cfg = K / '.config'
cs = cfg.read_text()
def set_y(name):
    global cs
    cs = re.sub(r'^CONFIG_'+re.escape(name)+r'=.*\n', '', cs, flags=re.M)
    cs = re.sub(r'^# CONFIG_'+re.escape(name)+r' is not set\n', '', cs, flags=re.M)
    cs += 'CONFIG_'+name+'=y\n'
for opt in ('MTD','MTD_BLOCK','MTD_PARTITIONS','MTD_CMDLINE_PARTS','MTD_NAND','MTD_NAND_IDS','YAFFS_FS','YAFFS_YAFFS2'):
    set_y(opt)
cfg.write_text(cs)

print('V3.48 FIX10 NAND parity patch installed')
print('  clock/reset: exact FIX10 register sequence')
print('  IRQ mask/clear: exact 0x201 / 0x7ff behavior')
print('  wait_int/wait_status: exact 0x2710 limits')
print('  NAND core + IDs + cmdline partitions: enabled')
