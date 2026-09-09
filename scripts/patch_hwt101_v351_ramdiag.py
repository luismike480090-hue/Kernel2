#!/usr/bin/env python3
from pathlib import Path
import re, sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch_hwt101_v351_ramdiag.py <kernel-root>')
K = Path(sys.argv[1])

# FIX10 /proc/iomem golden reference:
#   00000000-2cefffff : System RAM
#   2d000000-34ffffff : galcore managed memory
# This leaves 0x2cf00000-0x2cffffff outside both users.
# Use only the final 256 KiB of that 1 MiB gap.
RAMDIAG_START = 0x2cfc0000
RAMDIAG_SIZE  = 0x00040000
RAMDIAG_END   = RAMDIAG_START + RAMDIAG_SIZE - 1

# Register a standard Android ram_console platform device on the reserved DDR gap.
rc = K/'arch/arm/mach-k3v2/hwt101_ram_console.c'
rc.write_text(r'''/* HWT101 V3.51 persistent boot diagnostic RAM console. */
#include <linux/init.h>
#include <linux/ioport.h>
#include <linux/platform_device.h>

#define HWT101_RAMDIAG_START 0x2cfc0000
#define HWT101_RAMDIAG_SIZE  0x00040000

static struct resource hwt101_ramdiag_res = {
    .start = HWT101_RAMDIAG_START,
    .end   = HWT101_RAMDIAG_START + HWT101_RAMDIAG_SIZE - 1,
    .flags = IORESOURCE_MEM,
};

static struct platform_device hwt101_ramdiag_dev = {
    .name = "ram_console",
    .id = -1,
    .num_resources = 1,
    .resource = &hwt101_ramdiag_res,
};

static int __init hwt101_ramdiag_register(void)
{
    printk(KERN_INFO "HWTDIAG: RAMCONSOLE register phys=0x%08x size=0x%x\n",
           HWT101_RAMDIAG_START, HWT101_RAMDIAG_SIZE);
    return platform_device_register(&hwt101_ramdiag_dev);
}
arch_initcall(hwt101_ramdiag_register);
''')

mk = K/'arch/arm/mach-k3v2/Makefile'
m = mk.read_text()
line = 'obj-y += hwt101_ram_console.o\n'
if line not in m:
    m += '\n# HWT101 V3.51 persistent RAM boot diagnostics\n' + line
mk.write_text(m)

# Enable Android ram_console, verbose capture; no ECC and no early direct mapping.
cfg = K/'.config'
c = cfg.read_text()
def set_y(name):
    global c
    c = re.sub(rf'^CONFIG_{re.escape(name)}=.*\n', '', c, flags=re.M)
    c = re.sub(rf'^# CONFIG_{re.escape(name)} is not set\n', '', c, flags=re.M)
    c += f'CONFIG_{name}=y\n'
def set_n(name):
    global c
    c = re.sub(rf'^CONFIG_{re.escape(name)}=.*\n', '', c, flags=re.M)
    c = re.sub(rf'^# CONFIG_{re.escape(name)} is not set\n', '', c, flags=re.M)
    c += f'# CONFIG_{name} is not set\n'
set_y('ANDROID_RAM_CONSOLE')
set_y('ANDROID_RAM_CONSOLE_ENABLE_VERBOSE')
set_n('ANDROID_RAM_CONSOLE_ERROR_CORRECTION')
set_n('ANDROID_RAM_CONSOLE_EARLY_INIT')
cfg.write_text(c)

# Force initcall_debug internally.  This preserves the FIX10 boot-header cmdline
# while logging every initcall entry/return to the RAM console.
main = K/'init/main.c'
t = main.read_text()
if 'static bool initcall_debug;' not in t:
    raise SystemExit('initcall_debug anchor missing')
t = t.replace('static bool initcall_debug;', 'static bool initcall_debug = true; /* HWT101 V3.51 RAMDIAG */', 1)
main.write_text(t)

# Add high-signal checkpoints to the reconstructed HINAND path without changing
# register programming, IRQ logic, DMA logic, or NAND commands.
p = K/'drivers/mtd/nand/hinand_hwt101.c'
s = p.read_text()

def sub1(old, new, label):
    global s
    if old not in s:
        raise SystemExit('RAMDIAG anchor missing: '+label)
    s = s.replace(old, new, 1)

sub1('static int hinand_probe(struct platform_device*pdev){',
     'static int hinand_probe(struct platform_device*pdev){\n printk(KERN_EMERG "HWTDIAG: HINAND PROBE ENTER\\n");', 'probe-enter')
sub1('r0=platform_get_resource(pdev,IORESOURCE_MEM,0);',
     'printk(KERN_EMERG "HWTDIAG: HINAND before resources\\n");r0=platform_get_resource(pdev,IORESOURCE_MEM,0);', 'resources')
sub1('h->regs=ioremap_nocache(r0->start,resource_size(r0));',
     'printk(KERN_EMERG "HWTDIAG: HINAND resources irq=%d r0=%08lx r1=%08lx\\n",h->irq,(unsigned long)r0->start,(unsigned long)r1->start);h->regs=ioremap_nocache(r0->start,resource_size(r0));', 'ioremap')
sub1('h->dma_buf=dma_alloc_coherent(&pdev->dev,HWT_DMA_SIZE,&h->dma_handle,GFP_KERNEL);',
     'printk(KERN_EMERG "HWTDIAG: HINAND MMIO mapped regs=%p aux=%p\\n",h->regs,h->aux);h->dma_buf=dma_alloc_coherent(&pdev->dev,HWT_DMA_SIZE,&h->dma_handle,GFP_KERNEL);', 'dma')
sub1('hinand_init(&h->mtd);ret=request_irq',
     'printk(KERN_EMERG "HWTDIAG: HINAND before init\\n");hinand_init(&h->mtd);printk(KERN_EMERG "HWTDIAG: HINAND after init before IRQ\\n");ret=request_irq', 'init-irq')
sub1('printk(KERN_INFO"[hinand_probe] irq number is %x\\n",h->irq);',
     'printk(KERN_INFO"[hinand_probe] irq number is %x\\n",h->irq);printk(KERN_EMERG "HWTDIAG: HINAND IRQ OK before nand_scan\\n");', 'nandscan-before')
sub1('ret=nand_scan(&h->mtd,1);if(ret)',
     'ret=nand_scan(&h->mtd,1);printk(KERN_EMERG "HWTDIAG: HINAND nand_scan returned %d\\n",ret);if(ret)', 'nandscan-after')
sub1('nr_parts=parse_mtd_partitions(&h->mtd,part_probes,&parts,0);',
     'printk(KERN_EMERG "HWTDIAG: HINAND before parse/register MTD\\n");nr_parts=parse_mtd_partitions(&h->mtd,part_probes,&parts,0);', 'mtd-before')
sub1('if(ret)goto err_nand;return 0;',
     'printk(KERN_EMERG "HWTDIAG: HINAND mtd_device_register ret=%d parts=%d\\n",ret,nr_parts);if(ret)goto err_nand;printk(KERN_EMERG "HWTDIAG: HINAND PROBE PASS\\n");return 0;', 'probe-pass')

# Command-level markers: especially RESET / LBY / READID.
sub1('case NAND_CMD_READID:', 'case NAND_CMD_READID: printk(KERN_EMERG "HWTDIAG: NAND READID\\n");', 'readid')
sub1('case NAND_CMD_RESET:', 'case NAND_CMD_RESET: printk(KERN_EMERG "HWTDIAG: NAND RESET ENTER\\n");', 'reset')
sub1('printk(KERN_WARNING "lby mode=%x\\n", readb(h->aux));',
     'printk(KERN_WARNING "lby mode=%x\\n", readb(h->aux)); printk(KERN_EMERG "HWTDIAG: NAND LBY DONE value=%x\\n", readb(h->aux));', 'lby')

p.write_text(s)

print('V3.51 RAMDIAG installed')
print('RAMDIAG_START=0x%08x' % RAMDIAG_START)
print('RAMDIAG_END=0x%08x' % RAMDIAG_END)
print('RAMDIAG_SIZE=0x%08x' % RAMDIAG_SIZE)
print('ANDROID_RAM_CONSOLE=y verbose; persistent raw ring signature DBGC')
print('INITCALL_DEBUG=FORCED_ON inside kernel; FIX10 boot cmdline unchanged')
print('HINAND logic unchanged; diagnostic printk checkpoints only')
