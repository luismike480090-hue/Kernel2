#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch_hwt101_v364a_nand_diag_only.py <kernel-root>')

K = Path(sys.argv[1])
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
        "HWT101_V364A_HINAND_DIAG\n"
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

pairs = [
('printk(KERN_INFO"hinand_module_init: HWT101 reconstructed OEM path\\n");h=kzalloc(sizeof(*h),GFP_KERNEL);if(!h)return-ENOMEM;',
 'hwt_diag_stage=10;printk(KERN_INFO"hinand_module_init: HWT101 reconstructed OEM path\\n");h=kzalloc(sizeof(*h),GFP_KERNEL);if(!h){hwt_diag_stage=-10;return-ENOMEM;}'),
('r0=platform_get_resource(pdev,IORESOURCE_MEM,0);r1=platform_get_resource(pdev,IORESOURCE_MEM,1);h->irq=platform_get_irq(pdev,0);if(!r0||!r1||h->irq<0){ret=-ENODEV;goto err_free;}',
 'r0=platform_get_resource(pdev,IORESOURCE_MEM,0);r1=platform_get_resource(pdev,IORESOURCE_MEM,1);h->irq=platform_get_irq(pdev,0);hwt_diag_r0=!!r0;hwt_diag_r1=!!r1;hwt_diag_irq=h->irq;hwt_diag_stage=20;if(!r0||!r1||h->irq<0){hwt_diag_stage=-20;ret=-ENODEV;goto err_free;}'),
('h->regs=ioremap_nocache(r0->start,resource_size(r0));h->aux=ioremap_nocache(r1->start,resource_size(r1));if(!h->regs||!h->aux){ret=-EIO;goto err_map;}',
 'h->regs=ioremap_nocache(r0->start,resource_size(r0));h->aux=ioremap_nocache(r1->start,resource_size(r1));hwt_diag_map0=!!h->regs;hwt_diag_map1=!!h->aux;hwt_diag_stage=30;if(!h->regs||!h->aux){hwt_diag_stage=-30;ret=-EIO;goto err_map;}'),
('h->dma_buf=dma_alloc_coherent(&pdev->dev,HWT_DMA_SIZE,&h->dma_handle,GFP_KERNEL);if(!h->dma_buf){ret=-ENOMEM;goto err_map;}memset(h->dma_buf,0xff,HWT_DMA_SIZE);',
 'h->dma_buf=dma_alloc_coherent(&pdev->dev,HWT_DMA_SIZE,&h->dma_handle,GFP_KERNEL);hwt_diag_dma=!!h->dma_buf;hwt_diag_stage=40;if(!h->dma_buf){hwt_diag_stage=-40;ret=-ENOMEM;goto err_map;}memset(h->dma_buf,0xff,HWT_DMA_SIZE);'),
('hinand_init(&h->mtd);ret=request_irq(h->irq,hinand_irq,IRQF_DISABLED,"hisi_nand",h);if(ret)goto err_dma;printk(KERN_INFO"[hinand_probe] irq number is %x\\n",h->irq);printk(KERN_INFO"[hinand_probe] irq enable is %x\\n",nfc_read(h,NFC_INTEN));ret=nand_scan(&h->mtd,1);if(ret){ret=-ENXIO;goto err_irq;}',
 'hinand_init(&h->mtd);hwt_diag_con=nfc_read(h,NFC_CON);hwt_diag_status=nfc_read(h,NFC_STATUS);hwt_diag_inten=nfc_read(h,NFC_INTEN);hwt_diag_ints=nfc_read(h,NFC_INTS);hwt_diag_stage=45;ret=request_irq(h->irq,hinand_irq,IRQF_DISABLED,"hisi_nand",h);hwt_diag_request_irq=ret;if(ret){hwt_diag_stage=-50;goto err_dma;}hwt_diag_stage=50;printk(KERN_INFO"[hinand_probe] irq number is %x\\n",h->irq);printk(KERN_INFO"[hinand_probe] irq enable is %x\\n",nfc_read(h,NFC_INTEN));ret=nand_scan(&h->mtd,1);hwt_diag_nand_scan=ret;if(ret){hwt_diag_stage=-60;ret=-ENXIO;goto err_irq;}hwt_diag_stage=60;'),
('nr_parts=parse_mtd_partitions(&h->mtd,part_probes,&parts,0);ret=nr_parts>0?mtd_device_register(&h->mtd,parts,nr_parts):mtd_device_register(&h->mtd,NULL,0);if(ret)goto err_nand;return 0;',
 'nr_parts=parse_mtd_partitions(&h->mtd,part_probes,&parts,0);hwt_diag_nr_parts=nr_parts;hwt_diag_stage=70;ret=nr_parts>0?mtd_device_register(&h->mtd,parts,nr_parts):mtd_device_register(&h->mtd,NULL,0);hwt_diag_mtd_register=ret;if(ret){hwt_diag_stage=-80;goto err_nand;}hwt_diag_stage=100;return 0;'),
('static int __init hinand_module_init(void){int ret=platform_device_register(&hwt_hinand_device);if(ret)return ret;ret=platform_driver_register(&hwt_hinand_driver);if(ret)platform_device_unregister(&hwt_hinand_device);return ret;} module_init(hinand_module_init);',
 'static int __init hinand_module_init(void){int ret;create_proc_read_entry("hwt_hinand_diag",0444,NULL,hwt_hinand_diag_read,NULL);hwt_diag_stage=1;ret=platform_device_register(&hwt_hinand_device);if(ret){hwt_diag_stage=-1;return ret;}hwt_diag_stage=2;ret=platform_driver_register(&hwt_hinand_driver);if(ret){hwt_diag_stage=-2;platform_device_unregister(&hwt_hinand_device);}return ret;} module_init(hinand_module_init);')
]
for old,new in pairs:
    if old not in h:
        raise SystemExit('NAND diag anchor missing: '+old[:70])
    h = h.replace(old,new,1)

hp.write_text(h)
for required in ('hwt_hinand_diag_read','create_proc_read_entry("hwt_hinand_diag",0444','HWT101_V364A_HINAND_DIAG','hwt_diag_nand_scan','hwt_diag_request_irq'):
    if required not in hp.read_text():
        raise SystemExit('NAND diag gate failed: '+required)

print('V364A_NAND_DIAG_ONLY=PASS')
print('MEMORY_LAYOUT=UNCHANGED_FROM_V363')
print('DISPLAY_LAYOUT=UNCHANGED_FROM_V363')
print('PROC_DIAG=/proc/hwt_hinand_diag')
