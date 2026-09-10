#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch_hwt101_v364_mem_nand_diag.py <kernel-root>')

K = Path(sys.argv[1])

# ---------------------------------------------------------------------------
# 1) OEM MEMORY PARITY
# Recovered from the physically working HWT101 OEM early kernel log:
#   System RAM        00000000-2cefffff
#   GPU               160497664 @ 0x2d000000
#   codec              28311552 @ 0x36910000
#   camera                 4096 @ 0x38410000
#   gralloc             58720256 @ 0x38411000
#   overlay             67108864 @ 0x3bc11000
#   dumplog              2097152 @ 0x3fc11000
# VPP and dedicated FB reserve are zero in that observed allocation chain.
# ---------------------------------------------------------------------------
hm = K / 'arch/arm/mach-k3v2/include/mach/hisi_mem.h'
s = hm.read_text()

# Fix the Toshiba geometry globally, not only in the panel driver.
old = '#ifdef CONFIG_LCD_TOSHIBA_MDW70\n#define LCD_XRES\t(720)\n#define LCD_YRES\t(1280)'
new = '#ifdef CONFIG_LCD_TOSHIBA_MDW70\n#define LCD_XRES\t(1280)\n#define LCD_YRES\t(800)'
if old not in s:
    raise SystemExit('Toshiba hisi_mem geometry anchor missing')
s = s.replace(old, new, 1)

# Override donor media reservations with exact values observed in the OEM log.
anchor = '\n\n/* framebuffer */\n#define HISI_FRAME_BUFFER_BASE    (hisi_reserved_fb_phymem)\n'
if anchor not in s:
    raise SystemExit('hisi_mem framebuffer anchor missing')
override = r'''

/* HWT101 V3.64: exact OEM media reservation parity. */
#undef HIGPU_BUF_SIZE
#define HIGPU_BUF_SIZE              (160497664UL)
#undef HISI_MEM_GPU_SIZE
#define HISI_MEM_GPU_SIZE           (160497664UL)
#undef HISI_MEM_CODEC_SIZE
#define HISI_MEM_CODEC_SIZE         (28311552UL)
#undef HISI_MEM_VPP_SIZE
#define HISI_MEM_VPP_SIZE           (0UL)
#undef HISI_PMEM_CAMERA_SIZE
#define HISI_PMEM_CAMERA_SIZE       (4096UL)
#undef HISI_PMEM_GRALLOC_SIZE
#define HISI_PMEM_GRALLOC_SIZE      (58720256UL)
#undef HISI_PMEM_OVERLAY_SIZE
#define HISI_PMEM_OVERLAY_SIZE      (67108864UL)
#undef HISI_MEM_FB_SIZE
#define HISI_MEM_FB_SIZE            (0UL)
#undef HISI_PMEM_DUMPLOG_SIZE
#define HISI_PMEM_DUMPLOG_SIZE      (2097152UL)
'''
s = s.replace(anchor, override + anchor, 1)
hm.write_text(s)

# ---------------------------------------------------------------------------
# 2) NAND PROBE DIAGNOSTIC
# Behaviour is intentionally unchanged.  A world-readable /proc node records
# exactly how far probe got and the return codes.  adb pull can read it without
# /system/bin/sh or su.
# ---------------------------------------------------------------------------
hp = K / 'drivers/mtd/nand/hinand_hwt101.c'
h = hp.read_text()

inc = '#include <linux/mtd/partitions.h>\n'
if inc not in h:
    raise SystemExit('hinand include anchor missing')
h = h.replace(inc, inc + '#include <linux/proc_fs.h>\n', 1)

anchor = 'static inline u32 nfc_read(struct hwt_hinand *h, unsigned int reg)'
if anchor not in h:
    raise SystemExit('hinand nfc_read anchor missing')
diag = r'''
static int hwt_diag_stage;
static int hwt_diag_irq = -999;
static int hwt_diag_r0;
static int hwt_diag_r1;
static int hwt_diag_map0;
static int hwt_diag_map1;
static int hwt_diag_dma;
static int hwt_diag_request_irq = -999;
static int hwt_diag_nand_scan = -999;
static int hwt_diag_nr_parts = -999;
static int hwt_diag_mtd_register = -999;
static u32 hwt_diag_con;
static u32 hwt_diag_status;
static u32 hwt_diag_inten;
static u32 hwt_diag_ints;

static int hwt_hinand_diag_read(char *page, char **start, off_t off,
                                int count, int *eof, void *data)
{
    int len;
    len = scnprintf(page, count,
        "HWT101_V364_HINAND_DIAG\n"
        "stage=%d\nirq=%d\nresource0=%d\nresource1=%d\n"
        "ioremap0=%d\nioremap1=%d\ndma=%d\nrequest_irq_ret=%d\n"
        "nand_scan_ret=%d\nnr_parts=%d\nmtd_register_ret=%d\n"
        "NFC_CON=0x%08x\nNFC_STATUS=0x%08x\nNFC_INTEN=0x%08x\nNFC_INTS=0x%08x\n",
        hwt_diag_stage, hwt_diag_irq, hwt_diag_r0, hwt_diag_r1,
        hwt_diag_map0, hwt_diag_map1, hwt_diag_dma,
        hwt_diag_request_irq, hwt_diag_nand_scan,
        hwt_diag_nr_parts, hwt_diag_mtd_register,
        hwt_diag_con, hwt_diag_status, hwt_diag_inten, hwt_diag_ints);
    *eof = 1;
    return len;
}

'''
h = h.replace(anchor, diag + anchor, 1)

# Probe stages.  These replacements match the reconstructed/golden source.
old = 'printk(KERN_INFO"hinand_module_init: HWT101 reconstructed OEM path\\n");h=kzalloc(sizeof(*h),GFP_KERNEL);if(!h)return-ENOMEM;'
new = 'hwt_diag_stage=10;printk(KERN_INFO"hinand_module_init: HWT101 reconstructed OEM path\\n");h=kzalloc(sizeof(*h),GFP_KERNEL);if(!h){hwt_diag_stage=-10;return-ENOMEM;}'
if old not in h: raise SystemExit('hinand probe stage10 anchor missing')
h = h.replace(old, new, 1)

old = 'r0=platform_get_resource(pdev,IORESOURCE_MEM,0);r1=platform_get_resource(pdev,IORESOURCE_MEM,1);h->irq=platform_get_irq(pdev,0);if(!r0||!r1||h->irq<0){ret=-ENODEV;goto err_free;}'
new = 'r0=platform_get_resource(pdev,IORESOURCE_MEM,0);r1=platform_get_resource(pdev,IORESOURCE_MEM,1);h->irq=platform_get_irq(pdev,0);hwt_diag_r0=!!r0;hwt_diag_r1=!!r1;hwt_diag_irq=h->irq;hwt_diag_stage=20;if(!r0||!r1||h->irq<0){hwt_diag_stage=-20;ret=-ENODEV;goto err_free;}'
if old not in h: raise SystemExit('hinand resource anchor missing')
h = h.replace(old, new, 1)

old = 'h->regs=ioremap_nocache(r0->start,resource_size(r0));h->aux=ioremap_nocache(r1->start,resource_size(r1));if(!h->regs||!h->aux){ret=-EIO;goto err_map;}'
new = 'h->regs=ioremap_nocache(r0->start,resource_size(r0));h->aux=ioremap_nocache(r1->start,resource_size(r1));hwt_diag_map0=!!h->regs;hwt_diag_map1=!!h->aux;hwt_diag_stage=30;if(!h->regs||!h->aux){hwt_diag_stage=-30;ret=-EIO;goto err_map;}'
if old not in h: raise SystemExit('hinand ioremap anchor missing')
h = h.replace(old, new, 1)

old = 'h->dma_buf=dma_alloc_coherent(&pdev->dev,HWT_DMA_SIZE,&h->dma_handle,GFP_KERNEL);if(!h->dma_buf){ret=-ENOMEM;goto err_map;}memset(h->dma_buf,0xff,HWT_DMA_SIZE);'
new = 'h->dma_buf=dma_alloc_coherent(&pdev->dev,HWT_DMA_SIZE,&h->dma_handle,GFP_KERNEL);hwt_diag_dma=!!h->dma_buf;hwt_diag_stage=40;if(!h->dma_buf){hwt_diag_stage=-40;ret=-ENOMEM;goto err_map;}memset(h->dma_buf,0xff,HWT_DMA_SIZE);'
if old not in h: raise SystemExit('hinand dma anchor missing')
h = h.replace(old, new, 1)

old = 'hinand_init(&h->mtd);ret=request_irq(h->irq,hinand_irq,IRQF_DISABLED,"hisi_nand",h);if(ret)goto err_dma;printk(KERN_INFO"[hinand_probe] irq number is %x\\n",h->irq);printk(KERN_INFO"[hinand_probe] irq enable is %x\\n",nfc_read(h,NFC_INTEN));ret=nand_scan(&h->mtd,1);if(ret){ret=-ENXIO;goto err_irq;}'
new = 'hinand_init(&h->mtd);hwt_diag_con=nfc_read(h,NFC_CON);hwt_diag_status=nfc_read(h,NFC_STATUS);hwt_diag_inten=nfc_read(h,NFC_INTEN);hwt_diag_ints=nfc_read(h,NFC_INTS);hwt_diag_stage=45;ret=request_irq(h->irq,hinand_irq,IRQF_DISABLED,"hisi_nand",h);hwt_diag_request_irq=ret;if(ret){hwt_diag_stage=-50;goto err_dma;}hwt_diag_stage=50;printk(KERN_INFO"[hinand_probe] irq number is %x\\n",h->irq);printk(KERN_INFO"[hinand_probe] irq enable is %x\\n",nfc_read(h,NFC_INTEN));ret=nand_scan(&h->mtd,1);hwt_diag_nand_scan=ret;if(ret){hwt_diag_stage=-60;ret=-ENXIO;goto err_irq;}hwt_diag_stage=60;'
if old not in h: raise SystemExit('hinand request_irq/nand_scan anchor missing')
h = h.replace(old, new, 1)

old = 'nr_parts=parse_mtd_partitions(&h->mtd,part_probes,&parts,0);ret=nr_parts>0?mtd_device_register(&h->mtd,parts,nr_parts):mtd_device_register(&h->mtd,NULL,0);if(ret)goto err_nand;return 0;'
new = 'nr_parts=parse_mtd_partitions(&h->mtd,part_probes,&parts,0);hwt_diag_nr_parts=nr_parts;hwt_diag_stage=70;ret=nr_parts>0?mtd_device_register(&h->mtd,parts,nr_parts):mtd_device_register(&h->mtd,NULL,0);hwt_diag_mtd_register=ret;if(ret){hwt_diag_stage=-80;goto err_nand;}hwt_diag_stage=100;return 0;'
if old not in h: raise SystemExit('hinand mtd registration anchor missing')
h = h.replace(old, new, 1)

old = 'static int __init hinand_module_init(void){int ret=platform_device_register(&hwt_hinand_device);if(ret)return ret;ret=platform_driver_register(&hwt_hinand_driver);if(ret)platform_device_unregister(&hwt_hinand_device);return ret;} module_init(hinand_module_init);'
new = 'static int __init hinand_module_init(void){int ret;create_proc_read_entry("hwt_hinand_diag",0444,NULL,hwt_hinand_diag_read,NULL);hwt_diag_stage=1;ret=platform_device_register(&hwt_hinand_device);if(ret){hwt_diag_stage=-1;return ret;}hwt_diag_stage=2;ret=platform_driver_register(&hwt_hinand_driver);if(ret){hwt_diag_stage=-2;platform_device_unregister(&hwt_hinand_device);}return ret;} module_init(hinand_module_init);'
if old not in h: raise SystemExit('hinand module_init anchor missing')
h = h.replace(old, new, 1)

hp.write_text(h)

# Hard source checks.
for required in (
    '#define LCD_XRES\t(1280)', '#define LCD_YRES\t(800)',
    '#define HISI_MEM_GPU_SIZE           (160497664UL)',
    '#define HISI_MEM_CODEC_SIZE         (28311552UL)',
    '#define HISI_MEM_VPP_SIZE           (0UL)',
    '#define HISI_PMEM_GRALLOC_SIZE      (58720256UL)',
    '#define HISI_PMEM_OVERLAY_SIZE      (67108864UL)',
    '#define HISI_MEM_FB_SIZE            (0UL)',
):
    if required not in hm.read_text():
        raise SystemExit('memory parity gate failed: '+required)
for required in ('hwt_hinand_diag_read', 'create_proc_read_entry("hwt_hinand_diag",0444', 'hwt_diag_nand_scan', 'hwt_diag_request_irq'):
    if required not in hp.read_text():
        raise SystemExit('NAND diag gate failed: '+required)

print('V364_MEMORY_PARITY=PASS')
print('OEM_VISIBLE_RAM_TARGET=719MB')
print('OEM_SYSTEM_RAM_END=0x2cefffff')
print('OEM_GPU_BASE=0x2d000000')
print('OEM_GPU_SIZE=160497664')
print('OEM_CODEC_SIZE=28311552')
print('OEM_GRALLOC_SIZE=58720256')
print('OEM_OVERLAY_SIZE=67108864')
print('OEM_VPP_SIZE=0')
print('OEM_FB_RESERVED_SIZE=0')
print('V364_HINAND_PROC_DIAG=PASS')
