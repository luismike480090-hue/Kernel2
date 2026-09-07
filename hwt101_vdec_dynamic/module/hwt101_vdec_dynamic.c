#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/clk.h>
#include <linux/err.h>
#include <linux/proc_fs.h>
#include <linux/uaccess.h>
#include <linux/string.h>

#define PROC_NAME "hwt101_vdec"

static struct clk *vdec_clk;
static struct proc_dir_entry *proc_entry;

static unsigned long normalize_rate(unsigned long v)
{
    if (v < 1000000UL)
        v *= 1000000UL;

    switch (v) {
    case 180000000UL:
    case 240000000UL:
    case 288000000UL:
    case 360000000UL:
    case 480000000UL:
        return v;
    default:
        return 0;
    }
}

static int vdec_read_proc(char *page, char **start, off_t off,
                          int count, int *eof, void *data)
{
    unsigned long rate;
    int len;

    if (!vdec_clk || IS_ERR(vdec_clk))
        return 0;

    rate = clk_get_rate(vdec_clk);
    len = snprintf(page, count,
                   "%lu\nallowed=180000000,240000000,288000000,360000000,480000000\n",
                   rate);
    *eof = 1;
    return len;
}

static int vdec_write_proc(struct file *file, const char __user *buffer,
                           unsigned long count, void *data)
{
    char tmp[32];
    unsigned long requested, safe_rate;
    long rounded;
    int ret;

    if (!vdec_clk || IS_ERR(vdec_clk))
        return -ENODEV;

    if (count == 0 || count >= sizeof(tmp))
        return -EINVAL;

    if (copy_from_user(tmp, buffer, count))
        return -EFAULT;

    tmp[count] = '\0';
    requested = simple_strtoul(tmp, NULL, 0);
    safe_rate = normalize_rate(requested);
    if (!safe_rate)
        return -EINVAL;

    rounded = clk_round_rate(vdec_clk, safe_rate);
    if (rounded != (long)safe_rate) {
        printk(KERN_WARNING "HWT101-VDEC-DYN: reject requested=%lu rounded=%ld\n",
               safe_rate, rounded);
        return -EINVAL;
    }

    ret = clk_set_rate(vdec_clk, safe_rate);
    if (ret) {
        printk(KERN_ERR "HWT101-VDEC-DYN: clk_set_rate(%lu) failed=%d\n",
               safe_rate, ret);
        return ret;
    }

    printk(KERN_INFO "HWT101-VDEC-DYN: requested=%lu actual=%lu\n",
           safe_rate, clk_get_rate(vdec_clk));
    return count;
}

static int __init hwt101_vdec_dynamic_init(void)
{
    vdec_clk = clk_get(NULL, "clk_vdec");
    if (IS_ERR(vdec_clk)) {
        printk(KERN_ERR "HWT101-VDEC-DYN: clk_get failed=%ld\n",
               PTR_ERR(vdec_clk));
        return PTR_ERR(vdec_clk);
    }

    proc_entry = create_proc_entry(PROC_NAME, 0666, NULL);
    if (!proc_entry) {
        clk_put(vdec_clk);
        vdec_clk = NULL;
        return -ENOMEM;
    }

    proc_entry->read_proc = vdec_read_proc;
    proc_entry->write_proc = vdec_write_proc;

    printk(KERN_INFO "HWT101-VDEC-DYN: loaded current=%lu control=/proc/%s\n",
           clk_get_rate(vdec_clk), PROC_NAME);
    return 0;
}

static void __exit hwt101_vdec_dynamic_exit(void)
{
    if (proc_entry)
        remove_proc_entry(PROC_NAME, NULL);

    if (vdec_clk && !IS_ERR(vdec_clk)) {
        clk_set_rate(vdec_clk, 180000000UL);
        printk(KERN_INFO "HWT101-VDEC-DYN: unload restore=%lu\n",
               clk_get_rate(vdec_clk));
        clk_put(vdec_clk);
    }
}

module_init(hwt101_vdec_dynamic_init);
module_exit(hwt101_vdec_dynamic_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("HWT101 K3V2 dynamic safe VDEC clock controller");
MODULE_AUTHOR("HWT101 test build");
