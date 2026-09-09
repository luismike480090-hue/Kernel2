#!/usr/bin/env python3
from pathlib import Path
import re, sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch_hwt101_v353_autorecovery.py <kernel-root>')
K = Path(sys.argv[1])

# ---------------------------------------------------------------------------
# Extend the V3.52 journal protocol with timeout / boot-ok / watchdog markers.
# ---------------------------------------------------------------------------
hdr = K / 'include/linux/hwt101_bootdiag.h'
h = hdr.read_text()
if '#define HWT_EVT_TIMEOUT' not in h:
    h = h.replace('#define HWT_EVT_HINAND_BASE     0x00002000\n',
                  '#define HWT_EVT_HINAND_BASE     0x00002000\n'
                  '#define HWT_EVT_TIMEOUT         0x00003001\n'
                  '#define HWT_EVT_BOOT_OK         0x00003002\n'
                  '#define HWT_EVT_WDT_ARM         0x00003003\n'
                  '#define HWT_EVT_RECOVERY_MARK   0x00003004\n')
if 'int hwt101_diag_pending(void);' not in h:
    h = h.replace('void hwt101_diag_event(u32 type, u32 a, u32 b);\n',
                  'void hwt101_diag_event(u32 type, u32 a, u32 b);\n'
                  'int hwt101_diag_pending(void);\n')
hdr.write_text(h)

# ---------------------------------------------------------------------------
# Replace only the V3.52 journal implementation. Keep the same physical RAM
# journal, but add a software recovery timeout and /sys/kernel/.../boot_ok.
# No NAND writes are performed by this code.
# ---------------------------------------------------------------------------
cfile = K / 'arch/arm/mach-k3v2/hwt101_bootdiag.c'
cfile.write_text(r'''/* HWT101 V3.53 persistent boot journal + automatic warm recovery. */
#include <linux/init.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/io.h>
#include <linux/spinlock.h>
#include <linux/workqueue.h>
#include <linux/jiffies.h>
#include <linux/reboot.h>
#include <linux/kobject.h>
#include <linux/sysfs.h>
#include <linux/string.h>
#include <linux/hwt101_bootdiag.h>

#define HWT_MAGIC       0x33445748U /* "HWD3" LE */
#define HWT_VERSION     0x00035301U
#define HWT_HEADER_SIZE 0x40
#define HWT_REC_SIZE    16
#define HWT_CAPACITY    ((HWTDIAG_SIZE-HWT_HEADER_SIZE)/HWT_REC_SIZE)
#define HWT_SOFT_TIMEOUT_SEC 60

static void __iomem *hwt_base;
static u32 hwt_seq;
static u32 hwt_index;
static int hwt_pending = 1;
static DEFINE_SPINLOCK(hwt_lock);
static struct delayed_work hwt_recovery_work;
static struct kobject *hwt_kobj;

extern void hwt101_set_recovery_reason(int enable);
extern void hwt101_diag_wdt_disarm(void);

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

int hwt101_diag_pending(void)
{
    return hwt_pending;
}
EXPORT_SYMBOL(hwt101_diag_pending);

static void hwt101_timeout_recovery(struct work_struct *work)
{
    if (!hwt_pending)
        return;
    hwt101_diag_event(HWT_EVT_TIMEOUT, HWT_SOFT_TIMEOUT_SEC, 0);
    hwt101_set_recovery_reason(1);
    hwt101_diag_event(HWT_EVT_RECOVERY_MARK, 0x02, 1);
    wmb();
    printk(KERN_EMERG "HWTDIAG3: %u sec timeout -> warm reboot recovery\n",
           HWT_SOFT_TIMEOUT_SEC);
    kernel_restart("recovery");
}

static ssize_t boot_ok_store(struct kobject *kobj,
                             struct kobj_attribute *attr,
                             const char *buf, size_t count)
{
    if (count && buf[0] == '1') {
        hwt_pending = 0;
        cancel_delayed_work_sync(&hwt_recovery_work);
        hwt101_diag_wdt_disarm();
        hwt101_set_recovery_reason(0);
        hwt101_diag_event(HWT_EVT_BOOT_OK, 1, 0);
        printk(KERN_EMERG "HWTDIAG3: Android BOOT_OK - recovery watchdog cancelled\n");
    }
    return count;
}

static struct kobj_attribute boot_ok_attr =
    __ATTR(boot_ok, 0200, NULL, boot_ok_store);

static int __init hwt101_bootdiag_init(void)
{
    int rc;

    hwt_base = ioremap_nocache(HWTDIAG_BASE, HWTDIAG_SIZE);
    if (!hwt_base)
        return -ENOMEM;

    hwt_seq = 0;
    hwt_index = 0;
    hwt_pending = 1;
    hwt_wr(0x00, HWT_MAGIC);
    hwt_wr(0x04, HWT_VERSION);
    hwt_wr(0x08, 0);
    hwt_wr(0x0c, 0);
    hwt_wr(0x10, HWTDIAG_BASE);
    hwt_wr(0x14, HWTDIAG_SIZE);
    hwt_wr(0x18, HWT_CAPACITY);
    hwt_wr(0x1c, 0x4155544fU); /* AUTO */
    wmb();

    hwt101_diag_event(HWT_EVT_BOOT_READY, 0, 0);

    /* Pre-mark recovery. If the hardware watchdog resets us before the
     * software timeout can run, the bootloader still sees recovery=0x02. */
    hwt101_set_recovery_reason(1);
    hwt101_diag_event(HWT_EVT_RECOVERY_MARK, 0x02, 0);

    INIT_DELAYED_WORK(&hwt_recovery_work, hwt101_timeout_recovery);
    schedule_delayed_work(&hwt_recovery_work, HWT_SOFT_TIMEOUT_SEC * HZ);

    hwt_kobj = kobject_create_and_add("hwt101_bootdiag", kernel_kobj);
    if (hwt_kobj) {
        rc = sysfs_create_file(hwt_kobj, &boot_ok_attr.attr);
        if (rc)
            printk(KERN_WARNING "HWTDIAG3: boot_ok sysfs create failed=%d\n", rc);
    }

    printk(KERN_EMERG "HWTDIAG3: journal ready phys=0x%08lx size=0x%lx timeout=%us\n",
           HWTDIAG_BASE, HWTDIAG_SIZE, HWT_SOFT_TIMEOUT_SEC);
    return 0;
}
arch_initcall(hwt101_bootdiag_init);
''')

# ---------------------------------------------------------------------------
# K3V2 reset reason: expose the exact OEM scratch register already used by
# _k3v2oem1_reset(). 0x02=recovery, 0x10=coldboot/cleared diagnostic state.
# ---------------------------------------------------------------------------
pm = K / 'arch/arm/mach-k3v2/pm.c'
p = pm.read_text()
if 'void hwt101_set_recovery_reason(int enable)' not in p:
    anchor = 'static void _k3v2oem1_reset(char mode, const char *cmd)\n'
    if anchor not in p:
        raise SystemExit('pm.c reset anchor missing')
    helper = r'''void hwt101_set_recovery_reason(int enable)
{
    unsigned long num;
    num = enable ? find_rebootmap("recovery") : find_rebootmap(RESET_COLD_FLAG);
    writel(num, SECRAM_RESET_ADDR);
    wmb();
}
EXPORT_SYMBOL(hwt101_set_recovery_reason);

'''
    p = p.replace(anchor, helper + anchor, 1)
pm.write_text(p)

# ---------------------------------------------------------------------------
# K3V2 hardware watchdog backup. The stock driver continuously reloads the
# watchdog from per-CPU threads. In diagnostic mode we stop those feeders,
# load 30 s and leave RESET enabled. SP805-style hardware can then recover a
# kernel whose software workqueue is no longer running. boot_ok disarms it.
# ---------------------------------------------------------------------------
wd = K / 'drivers/watchdog/hisik3_wdt.c'
w = wd.read_text()
if '#include <linux/hwt101_bootdiag.h>' not in w:
    inc = '#include <linux/err.h>\n'
    if inc not in w:
        raise SystemExit('watchdog include anchor missing')
    w = w.replace(inc, inc + '#include <linux/hwt101_bootdiag.h>\n', 1)

if 'void hwt101_diag_wdt_disarm(void)' not in w:
    anchor = 'static ssize_t hisik3_wdt_write(struct file *file, const char *data,\n'
    if anchor not in w:
        raise SystemExit('watchdog disarm insertion anchor missing')
    helper = r'''void hwt101_diag_wdt_disarm(void)
{
    if (!wdt)
        return;
    wdt_disable();
}
EXPORT_SYMBOL(hwt101_diag_wdt_disarm);

'''
    w = w.replace(anchor, helper + anchor, 1)

old = '''\twdt_enable();\n\n        dev_warn(&pdev->dev,"WDT probing has been finished\\n");\n'''
new = '''\twdt_enable();\n\n\tif (hwt101_diag_pending()) {\n\t\t/* Diagnostic mode: do not feed forever. 30 s is the hardware\n\t\t * backup; software warm-recovery is scheduled for 60 s. */\n\t\tk3_wdt_kick_stop();\n\t\twdt_config(30);\n\t\twdt_enable();\n\t\thwt101_diag_event(HWT_EVT_WDT_ARM, 30, 0);\n\t\tdev_warn(&pdev->dev, "HWTDIAG3 hardware recovery watchdog armed\\n");\n\t}\n\n        dev_warn(&pdev->dev,"WDT probing has been finished\\n");\n'''
if 'HWTDIAG3 hardware recovery watchdog armed' not in w:
    if old not in w:
        raise SystemExit('watchdog probe-end anchor missing')
    w = w.replace(old, new, 1)
wd.write_text(w)

print('V3.53 automatic recovery diagnostic installed')
print('SOFT_TIMEOUT_SEC=60')
print('HARDWARE_WDT_LOAD_SEC=30')
print('RECOVERY_REASON=0x02 pre-armed')
print('BOOT_OK=/sys/kernel/hwt101_bootdiag/boot_ok')
print('NO NAND diagnostic writes added')
