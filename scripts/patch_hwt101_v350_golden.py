#!/usr/bin/env python3
from pathlib import Path
import re, runpy, sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_hwt101_v350_golden.py <kernel-root>")
K = Path(sys.argv[1])
saved = sys.argv[:]
try:
    sys.argv = ["scripts/add_hwt101_hinand_v340.py", str(K)]
    runpy.run_path("scripts/add_hwt101_hinand_v340.py", run_name="__main__")
finally:
    sys.argv = saved

P = K / "drivers/mtd/nand/hinand_hwt101.c"
s = P.read_text()
anchor = "#define NFC_DMA_LEN   0x80\n"
insert = """#define NFC_DMA_LEN   0x80

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
"""
if anchor not in s: raise SystemExit("NFC register anchor missing")
s = s.replace(anchor, insert, 1)

old='static int hwt_wait_status(struct hwt_hinand *h) { int n=1000000; while (!(nfc_read(h,NFC_STATUS)&1) && --n) cpu_relax(); return n?0:-ETIMEDOUT; }'
new="""static int hwt_wait_status(struct hwt_hinand *h)
{
    int n = 0x2710;
    u32 st;
    do {
        st = nfc_read(h, NFC_STATUS);
        if (st & 1)
            return (int)st;
        cpu_relax();
    } while (--n);
    printk(KERN_ERR \"NANDC : wait_op_done timeout\\n\");
    return -ETIMEDOUT;
}"""
if old not in s: raise SystemExit("wait_status anchor missing")
s=s.replace(old,new,1)

old='static irqreturn_t hinand_irq(int irq, void *dev_id) { struct hwt_hinand *h=dev_id; u32 s=nfc_read(h,NFC_INTS); nfc_write(h,0,NFC_INTEN); nfc_write(h,s&0x7ff,NFC_INTCLR); complete(&h->done); return IRQ_HANDLED; }'
new="""static irqreturn_t hinand_irq(int irq, void *dev_id)
{
    struct hwt_hinand *h = dev_id;
    u32 status = nfc_read(h, NFC_INTS);
    nfc_write(h, 0, NFC_INTEN);
    nfc_write(h, 0x7ff, NFC_INTCLR);
    if (status & 0x201)
        complete(&h->done);
    return IRQ_HANDLED;
}"""
if old not in s: raise SystemExit("irq anchor missing")
s=s.replace(old,new,1)

old='static int hwt_wait_int(struct hwt_hinand *h) { unsigned long t; reinit_completion(&h->done); t=wait_for_completion_timeout(&h->done,msecs_to_jiffies(1000)); return t?0:-ETIMEDOUT; }'
new="""static int hwt_wait_int(struct hwt_hinand *h)
{
    unsigned long t = wait_for_completion_timeout(&h->done, 0x2710);
    if (t)
        return 0;
    printk(KERN_ERR \"command execution timed out\\n\");
    return -ETIMEDOUT;
}"""
if old not in s: raise SystemExit("wait_int anchor missing")
s=s.replace(old,new,1)
s=s.replace('if(hwt_wait_int(h)) hwt_wait_status(h); h->addr_cycle=0;', 'hwt_wait_int(h); h->addr_cycle=0;')
s=s.replace('if(hwt_wait_int(h)) hwt_wait_status(h); break;', 'hwt_wait_int(h); break;')

reset_old='case NAND_CMD_RESET: hwt_clear_int(h); nfc_write(h,1,NFC_INTEN); nfc_write(h,NAND_CMD_RESET,NFC_CMD); nfc_write(h,0x44,NFC_OP); hwt_wait_status(h); break;'
reset_new="""case NAND_CMD_RESET:
        hwt_clear_int(h);
        nfc_write(h, 1, NFC_INTEN);
        nfc_write(h, NAND_CMD_RESET, NFC_CMD);
        nfc_write(h, 0x44, NFC_OP);
        hwt_wait_status(h);

        /* FIX10: RESET -> feature 1 = 5 -> read/confirm LBY mode. */
        nfc_write(h, 0xef, NFC_CMD);
        nfc_write(h, 1, NFC_ADDRL);
        nfc_write(h, 0, NFC_ADDRH);
        nfc_write(h, 4, NFC_DATA_NUM);
        writeb(5, h->aux + 0);
        writeb(0, h->aux + 1);
        writeb(0, h->aux + 2);
        writeb(0, h->aux + 3);
        nfc_write(h, 0x274, NFC_OP);
        hwt_wait_status(h);

        writeb(0, h->aux + 0);
        writeb(0, h->aux + 1);
        writeb(0, h->aux + 2);
        writeb(0, h->aux + 3);
        nfc_write(h, 1, NFC_ADDRL);
        nfc_write(h, 0, NFC_ADDRH);
        nfc_write(h, 4, NFC_DATA_NUM);
        nfc_write(h, 0x266, NFC_OP);
        hwt_wait_status(h);
        printk(KERN_WARNING \"lby mode=%x\\n\", readb(h->aux));
        break;"""
if reset_old not in s: raise SystemExit("RESET anchor missing")
s=s.replace(reset_old,reset_new,1)

old='void hinand_init(struct mtd_info*mtd){struct nand_chip*c=mtd->priv;struct hwt_hinand*h=c->priv;nfc_write(h,0x47,NFC_CON);nfc_write(h,0,NFC_PWIDTH);nfc_write(h,3,NFC_DMA_CFG);nfc_write(h,0,NFC_INTEN);nfc_write(h,0x7ff,NFC_INTCLR);} EXPORT_SYMBOL(hinand_init);'
new="""void hinand_init(struct mtd_info *mtd)
{
    struct nand_chip *c = mtd->priv;
    struct hwt_hinand *h = c->priv;
    u32 v;
    v = readl(K3V2_NAND_EN_REG3);
    printk(KERN_INFO \"EN_REG3 value 0x%x\\n\", v);
    v |= 0x00080000;
    printk(KERN_INFO \"EN_REG3 value 0x%x\\n\", v);
    writel(v, K3V2_NAND_EN_REG3);
    v = readl(K3V2_NAND_RST_REG3);
    printk(KERN_INFO \"RST_REG3 value 0x%x\\n\", v);
    writel(0x00400000, K3V2_NAND_RST_REG3);
    writel(0x00400000, K3V2_NAND_RSTDIS_REG3);
    writel(0, K3V2_NAND_CFG0); writel(0, K3V2_NAND_CFG1);
    writel(0, K3V2_NAND_CFG2); writel(0, K3V2_NAND_CFG3);
    writel(0, K3V2_NAND_CFG4); writel(0, K3V2_NAND_CFG5);
    writel(0, K3V2_NAND_CFG6); writel(0, K3V2_NAND_CFG7);
    writel(0, K3V2_NAND_CFG8); mb();
    nfc_write(h, 0x47, NFC_CON);
    nfc_write(h, 0, NFC_PWIDTH);
    nfc_write(h, 3, NFC_DMA_CFG);
    nfc_write(h, 0, NFC_INTEN);
    nfc_write(h, 0x7ff, NFC_INTCLR);
}
EXPORT_SYMBOL(hinand_init);"""
if old not in s: raise SystemExit("hinand_init anchor missing")
s=s.replace(old,new,1)

old='h->chip.chip_delay=25;h->chip.options|=NAND_NO_AUTOINCR;'
new='h->chip.chip_delay=25;h->chip.options|=(NAND_NO_AUTOINCR|NAND_NO_READRDY|NAND_BROKEN_XD);'
if old not in s: raise SystemExit("chip options anchor missing")
s=s.replace(old,new,1)

old='ret=request_irq(h->irq,hinand_irq,IRQF_DISABLED,"hisi_nand",h);if(ret)goto err_dma;printk(KERN_INFO"hinand_probe: irq number is %x\\n",h->irq);ret=nand_scan(&h->mtd,1);'
new='ret=request_irq(h->irq,hinand_irq,IRQF_DISABLED,"hisi_nand",h);if(ret)goto err_dma;printk(KERN_INFO"[hinand_probe] irq number is %x\\n",h->irq);printk(KERN_INFO"[hinand_probe] irq enable is %x\\n",nfc_read(h,NFC_INTEN));ret=nand_scan(&h->mtd,1);'
if old not in s: raise SystemExit("probe request_irq anchor missing")
s=s.replace(old,new,1)
if 'reinit_completion' in s: raise SystemExit("reinit_completion survived")
P.write_text(s)

# Display link parity with FIX10 initcall order.
mk=K/'drivers/video/k3/Makefile'
m=mk.read_text()
oldmk='obj-$(CONFIG_FB_K3_CLCD) := k3fb.o'
if oldmk not in m: raise SystemExit('k3 Makefile anchor missing')
m=m.replace(oldmk,'obj-y := sn65dsi83_hwt101.o\nobj-$(CONFIG_FB_K3_CLCD) += k3fb.o',1)
m=re.sub(r'\s*panel/mipi_toshiba_MDY90\.o\s*$', '', m, flags=re.M)
# Fix continuation after removing the final donor panel.
m=m.replace('panel/mipi_cmi_PT045TN07.o \\\n\n','panel/mipi_cmi_PT045TN07.o\n\n')
mk.write_text(m)

print('V3.50 GOLDEN patch installed')
print('HINAND: FIX10 IRQ/MMIO/init/waits/options/LBY=5')
print('DISPLAY: SN65 before K3FB; donor MDY90 removed')
