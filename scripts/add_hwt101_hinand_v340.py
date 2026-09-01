#!/usr/bin/env python3
from pathlib import Path
import sys

K=Path(sys.argv[1] if len(sys.argv)>1 else 'kernel')
P=K/'drivers/mtd/nand/hinand_hwt101.c'
C=r'''/*
 * HWT101 / MS1211 HiSilicon NAND controller reconstruction.
 * Recovered from the known-good Huawei 3.0.8 HWT101 kernel ABI/register trace.
 */
#include <linux/init.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/slab.h>
#include <linux/io.h>
#include <linux/interrupt.h>
#include <linux/completion.h>
#include <linux/dma-mapping.h>
#include <linux/mtd/mtd.h>
#include <linux/mtd/nand.h>
#include <linux/mtd/partitions.h>
#include <linux/delay.h>

#define HWT_NFC_BASE       0xfd100000
#define HWT_NFC_END        0xfd1007ff
#define HWT_NFC_AUX_BASE   0xfd200000
#define HWT_NFC_AUX_END    0xfd2000af
#define HWT_NFC_IRQ        46
#define HWT_DMA_SIZE       0x3000
#define NFC_CON       0x00
#define NFC_PWIDTH    0x04
#define NFC_CMD       0x0c
#define NFC_ADDRL     0x10
#define NFC_ADDRH     0x14
#define NFC_DATA_NUM  0x18
#define NFC_OP        0x1c
#define NFC_STATUS    0x20
#define NFC_INTEN     0x24
#define NFC_INTS      0x28
#define NFC_INTCLR    0x2c
#define NFC_DMA_CTRL  0x60
#define NFC_DMA_ADDR  0x64
#define NFC_DMA_ADDR2 0x68
#define NFC_DMA_LEN2  0x6c
#define NFC_DMA_CFG   0x70
#define NFC_DMA_OFF   0x7c
#define NFC_DMA_LEN   0x80

struct hwt_hinand {
    struct nand_chip chip;
    struct mtd_info mtd;
    void __iomem *regs;
    void __iomem *aux;
    u8 *dma_buf;
    dma_addr_t dma_handle;
    struct completion done;
    int irq;
    u32 command;
    u32 addr_cycle;
    u32 addr[2];
    u32 column;
    u32 page_offset;
};
static inline u32 nfc_read(struct hwt_hinand *h, unsigned int reg) { return readl(h->regs + reg); }
static inline void nfc_write(struct hwt_hinand *h, u32 v, unsigned int reg) { writel(v, h->regs + reg); }
static int hinand_dev_ready(struct mtd_info *mtd) { return 1; }
static int hwt_wait_status(struct hwt_hinand *h) { int n=1000000; while (!(nfc_read(h,NFC_STATUS)&1) && --n) cpu_relax(); return n?0:-ETIMEDOUT; }
static irqreturn_t hinand_irq(int irq, void *dev_id) { struct hwt_hinand *h=dev_id; u32 s=nfc_read(h,NFC_INTS); nfc_write(h,0,NFC_INTEN); nfc_write(h,s&0x7ff,NFC_INTCLR); complete(&h->done); return IRQ_HANDLED; }
static int hwt_wait_int(struct hwt_hinand *h) { unsigned long t; reinit_completion(&h->done); t=wait_for_completion_timeout(&h->done,msecs_to_jiffies(1000)); return t?0:-ETIMEDOUT; }
static void hwt_clear_int(struct hwt_hinand *h) { nfc_write(h,0x7ff,NFC_INTCLR); }
static void hwt_set_addr(struct hwt_hinand *h) { nfc_write(h,h->addr[0]&0xffff0000,NFC_ADDRL); if(h->addr_cycle>4) nfc_write(h,h->addr[1],NFC_ADDRH); }
static void hwt_readstart(struct hwt_hinand *h) { hwt_clear_int(h); nfc_write(h,0x200,NFC_INTEN); nfc_write(h,0x3f,NFC_DMA_CFG); hwt_set_addr(h); nfc_write(h,HWT_DMA_SIZE,NFC_CMD); nfc_write(h,0x4c7,NFC_CON); nfc_write(h,0,NFC_DMA_OFF); nfc_write(h,0x21c0,NFC_DMA_LEN); nfc_write(h,(u32)h->dma_handle,NFC_DMA_ADDR); nfc_write(h,0x21,NFC_DMA_CTRL); if(hwt_wait_int(h)) hwt_wait_status(h); h->addr_cycle=0; }
static void hwt_pageprog(struct hwt_hinand *h) { hwt_clear_int(h); nfc_write(h,0x200,NFC_INTEN); nfc_write(h,0x3f,NFC_DMA_CFG); nfc_write(h,0x4c7,NFC_CON); nfc_write(h,(u32)h->dma_handle,NFC_DMA_ADDR); nfc_write(h,(u32)h->dma_handle+0x2000,NFC_DMA_ADDR2); nfc_write(h,0x01c00000,NFC_DMA_LEN2); hwt_set_addr(h); nfc_write(h,0x1080,NFC_CMD); nfc_write(h,0x23,NFC_DMA_CTRL); if(hwt_wait_int(h)) hwt_wait_status(h); h->addr_cycle=0; }
static void hinand_cmd_ctrl(struct mtd_info *mtd,int dat,unsigned int ctrl) {
    struct nand_chip *chip=mtd->priv; struct hwt_hinand *h=chip->priv; unsigned int idx,shift;
    if(ctrl&NAND_ALE){ if(ctrl&NAND_CTRL_CHANGE){h->addr_cycle=0;h->addr[0]=h->addr[1]=0;} idx=h->addr_cycle>=4; shift=(h->addr_cycle-(idx?4:0))*8; h->addr[idx]|=((u32)dat&0xff)<<shift; h->addr_cycle++; }
    if((ctrl&NAND_CLE)&&(ctrl&NAND_CTRL_CHANGE)){ h->command=dat&0xff; switch(h->command){
    case NAND_CMD_READSTART: hwt_readstart(h); break;
    case NAND_CMD_PAGEPROG: hwt_pageprog(h); break;
    case NAND_CMD_READID: hwt_clear_int(h); nfc_write(h,NAND_CMD_READID,NFC_CMD); nfc_write(h,0,NFC_ADDRL); nfc_write(h,0,NFC_ADDRH); nfc_write(h,0x266,NFC_OP); hwt_wait_status(h); memcpy(h->dma_buf,(void __force const *)h->aux,16); h->page_offset=0; break;
    case NAND_CMD_STATUS: nfc_write(h,0x00700000,NFC_CMD); nfc_write(h,0xc7,NFC_CON); nfc_write(h,5,NFC_OP); hwt_wait_status(h); break;
    case NAND_CMD_RESET: hwt_clear_int(h); nfc_write(h,1,NFC_INTEN); nfc_write(h,NAND_CMD_RESET,NFC_CMD); nfc_write(h,0x44,NFC_OP); hwt_wait_status(h); break;
    case NAND_CMD_ERASE2: hwt_clear_int(h); nfc_write(h,1,NFC_INTEN); nfc_write(h,0xc7,NFC_CON); nfc_write(h,3,NFC_DMA_CFG); nfc_write(h,h->addr[0],NFC_ADDRL); nfc_write(h,h->addr_cycle>4?h->addr[1]:0,NFC_ADDRH); nfc_write(h,0xd060,NFC_CMD); nfc_write(h,(h->addr_cycle<<9)|0x6d,NFC_OP); if(hwt_wait_int(h)) hwt_wait_status(h); break;
    default: break; }}
    if(dat==NAND_CMD_NONE && h->addr_cycle && (h->command==NAND_CMD_SEQIN || h->command==NAND_CMD_READ0)){ h->column=h->addr[0]&0xffff; h->page_offset=0; }
}
static u8 hinand_read_byte(struct mtd_info *mtd) { struct nand_chip *c=mtd->priv; struct hwt_hinand*h=c->priv; if(h->command==NAND_CMD_STATUS)return(nfc_read(h,NFC_STATUS)>>5)&0xff; return h->dma_buf[h->column+h->page_offset++]; }
static u16 hinand_read_word(struct mtd_info *mtd) { struct nand_chip*c=mtd->priv; struct hwt_hinand*h=c->priv; u16 v; memcpy(&v,h->dma_buf+h->column+h->page_offset,2); h->page_offset+=2; return v; }
static void hinand_read_buf(struct mtd_info*mtd,u8*buf,int len){struct nand_chip*c=mtd->priv;struct hwt_hinand*h=c->priv;memcpy(buf,h->dma_buf+h->column+h->page_offset,len);h->page_offset+=len;}
static void hinand_write_buf(struct mtd_info*mtd,const u8*buf,int len){struct nand_chip*c=mtd->priv;struct hwt_hinand*h=c->priv;memcpy(h->dma_buf+h->column+h->page_offset,buf,len);h->page_offset+=len;}
static void hinand_select_chip(struct mtd_info*mtd,int chipnr){struct nand_chip*c=mtd->priv;struct hwt_hinand*h=c->priv;if(chipnr<0)return;if(chipnr>4)BUG();nfc_write(h,chipnr<<7,NFC_OP);hwt_wait_status(h);}
void hinand_init(struct mtd_info*mtd){struct nand_chip*c=mtd->priv;struct hwt_hinand*h=c->priv;nfc_write(h,0x47,NFC_CON);nfc_write(h,0,NFC_PWIDTH);nfc_write(h,3,NFC_DMA_CFG);nfc_write(h,0,NFC_INTEN);nfc_write(h,0x7ff,NFC_INTCLR);} EXPORT_SYMBOL(hinand_init);
void printreg(struct hwt_hinand*h){unsigned int i;for(i=0;i<0x30;i+=4)printk(KERN_DEBUG"hinand: reg %x=%x\n",i,nfc_read(h,i));} EXPORT_SYMBOL(printreg);
static int hinand_probe(struct platform_device*pdev){
 struct hwt_hinand*h;struct resource*r0,*r1;static const char*part_probes[]={"cmdlinepart",NULL};struct mtd_partition*parts=NULL;int nr_parts,ret;
 printk(KERN_INFO"hinand_module_init: HWT101 reconstructed OEM path\n");h=kzalloc(sizeof(*h),GFP_KERNEL);if(!h)return-ENOMEM;
 r0=platform_get_resource(pdev,IORESOURCE_MEM,0);r1=platform_get_resource(pdev,IORESOURCE_MEM,1);h->irq=platform_get_irq(pdev,0);if(!r0||!r1||h->irq<0){ret=-ENODEV;goto err_free;}
 h->regs=ioremap_nocache(r0->start,resource_size(r0));h->aux=ioremap_nocache(r1->start,resource_size(r1));if(!h->regs||!h->aux){ret=-EIO;goto err_map;}
 h->dma_buf=dma_alloc_coherent(&pdev->dev,HWT_DMA_SIZE,&h->dma_handle,GFP_KERNEL);if(!h->dma_buf){ret=-ENOMEM;goto err_map;}memset(h->dma_buf,0xff,HWT_DMA_SIZE);
 init_completion(&h->done);platform_set_drvdata(pdev,h);h->chip.IO_ADDR_R=h->aux;h->chip.IO_ADDR_W=h->aux;h->chip.priv=h;h->mtd.priv=&h->chip;h->mtd.name=pdev->name;h->mtd.owner=THIS_MODULE;
 h->chip.cmd_ctrl=hinand_cmd_ctrl;h->chip.dev_ready=hinand_dev_ready;h->chip.select_chip=hinand_select_chip;h->chip.chip_delay=25;h->chip.options|=NAND_NO_AUTOINCR;h->chip.read_byte=hinand_read_byte;h->chip.read_word=hinand_read_word;h->chip.read_buf=hinand_read_buf;h->chip.write_buf=hinand_write_buf;h->chip.ecc.mode=NAND_ECC_NONE;
 hinand_init(&h->mtd);ret=request_irq(h->irq,hinand_irq,IRQF_DISABLED,"hisi_nand",h);if(ret)goto err_dma;printk(KERN_INFO"hinand_probe: irq number is %x\n",h->irq);ret=nand_scan(&h->mtd,1);if(ret){ret=-ENXIO;goto err_irq;}
 nr_parts=parse_mtd_partitions(&h->mtd,part_probes,&parts,0);ret=nr_parts>0?mtd_device_register(&h->mtd,parts,nr_parts):mtd_device_register(&h->mtd,NULL,0);if(ret)goto err_nand;return 0;
err_nand:nand_release(&h->mtd);err_irq:free_irq(h->irq,h);err_dma:dma_free_coherent(&pdev->dev,HWT_DMA_SIZE,h->dma_buf,h->dma_handle);err_map:if(h->aux)iounmap(h->aux);if(h->regs)iounmap(h->regs);err_free:kfree(h);return ret;}
int hinand_remove(struct platform_device*pdev){struct hwt_hinand*h=platform_get_drvdata(pdev);if(!h)return 0;nand_release(&h->mtd);free_irq(h->irq,h);dma_free_coherent(&pdev->dev,HWT_DMA_SIZE,h->dma_buf,h->dma_handle);iounmap(h->aux);iounmap(h->regs);platform_set_drvdata(pdev,NULL);kfree(h);return 0;} EXPORT_SYMBOL(hinand_remove);
static struct resource hwt_hinand_resources[]={
 {.start=HWT_NFC_BASE,.end=HWT_NFC_END,.flags=IORESOURCE_MEM},
 {.start=HWT_NFC_AUX_BASE,.end=HWT_NFC_AUX_END,.flags=IORESOURCE_MEM},
 {.start=HWT_NFC_IRQ,.end=HWT_NFC_IRQ,.flags=IORESOURCE_IRQ},};
static void hinand_platdev_release(struct device*dev){}
static struct platform_device hwt_hinand_device={.name="hisi_nand",.id=-1,.num_resources=ARRAY_SIZE(hwt_hinand_resources),.resource=hwt_hinand_resources,.dev={.release=hinand_platdev_release,},};
static struct platform_driver hwt_hinand_driver={.probe=hinand_probe,.remove=hinand_remove,.driver={.name="hisi_nand",.owner=THIS_MODULE,},};
static int __init hinand_module_init(void){int ret=platform_device_register(&hwt_hinand_device);if(ret)return ret;ret=platform_driver_register(&hwt_hinand_driver);if(ret)platform_device_unregister(&hwt_hinand_device);return ret;} module_init(hinand_module_init);
MODULE_LICENSE("GPL");MODULE_DESCRIPTION("Huawei HWT101 reconstructed HiSilicon NAND controller");
'''
P.write_text(C)
mk=K/'drivers/mtd/nand/Makefile'
t=mk.read_text()
line='obj-y += hinand_hwt101.o\n'
if line not in t: mk.write_text(t+'\n# HWT101 recovered NAND controller\n'+line)
print('Installed',P)
