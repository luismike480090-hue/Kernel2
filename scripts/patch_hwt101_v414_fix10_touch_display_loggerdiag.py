#!/usr/bin/env python3
from pathlib import Path
import re, sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else "kernel")

# ------------------------------------------------------------------
# V4.14: only concrete FIX10 parity deltas found after V4.13 hardware test.
# DO NOT change HSAD, battery, YAFFS/NAND guard, or framebuffer stride.
#
# Proven from the exact golden FIX10 binary:
#   Goodix I2C2 addr 0x14
#   Goodix platform_data: INT=157, RESET=156, ENABLE=61
#   gtp_reset_guitar:
#       RST=0, 20ms
#       INT=(addr == 0x14), 2ms
#       RST=1, 6ms
#       RST=input
#       INT=0, 50ms, INT=input
#       write 0x8041 = 0xAA
#   Toshiba 1280x800:
#       physical 230x149 mm
#       HBP/HFP/HSW = 60/70/60
#       VBP/VFP/VSW = 13/13/7
#       pixel clock = 76 MHz (already correct)
#       4 DSI lanes (already correct)
#       dsi_bit_clk = 228
#   SN65 main register table already matches FIX10 byte-for-byte.
#
# Logger:
#   FIX10 has CONFIG_K3_LOG=y, V4.13 does not.
#   This build DOES NOT enable K3_LOG yet. It adds bounded diagnostics only,
#   so hardware evidence can distinguish open/write/ring-reader failures.
# ------------------------------------------------------------------

# ------------------------------------------------------------------
# 1) DISPLAY: exact FIX10 Toshiba timings/geometry/DSI clock.
# ------------------------------------------------------------------
panel = root / "drivers/video/k3/panel/mipi_toshiba_MDW70_V001.c"
s = panel.read_text()

def set_all_assignment(src, field, value):
    pat = re.compile(r'(pinfo->' + re.escape(field) + r'\s*=\s*)[^;]+;')
    out, n = pat.subn(r'\g<1>' + str(value) + ';', src)
    if n < 1:
        raise SystemExit("display field missing: " + field)
    return out, n

# V4.12/V4.13 already changed active resolution to 1280x800.
# Reassert exact values as gates, without touching framebuffer stride.
for field, value in (
    ("xres", 1280),
    ("yres", 800),
    ("width", 230),
    ("height", 149),
    ("ldi.h_back_porch", 60),
    ("ldi.h_front_porch", 70),
    ("ldi.h_pulse_width", 60),
    ("ldi.v_back_porch", 13),
    ("ldi.v_front_porch", 13),
    ("ldi.v_pulse_width", 7),
    ("mipi.dsi_bit_clk", 228),
):
    s, _ = set_all_assignment(s, field, value)

# These values were already exact in V4.13; assert, don't alter semantically.
if not re.search(r'pinfo->clk_rate\s*=\s*76000000\s*;', s):
    raise SystemExit("FIX10 pixel clock anchor missing")
if not re.search(r'pinfo->mipi\.lane_nums\s*=\s*DSI_4_LANES\s*;', s):
    raise SystemExit("FIX10 4-lane anchor missing")

panel.write_text(s)

# ------------------------------------------------------------------
# 2) TOUCH: replace V4.13 retry-only shim with FIX10 hardware bootstrap.
# ------------------------------------------------------------------
g = root / "drivers/input/touchscreen/hwt101_goodix.c"
if not g.exists():
    raise SystemExit("V4.13 Goodix source missing")

src = r'''/*
 * HWT101 Goodix GT9280 compatibility driver V4.14.
 *
 * Hardware/bootstrap parity recovered from exact FIX10 golden binary:
 *   bus=2, addr=0x14
 *   INT=GPIO157 (GPIO_19_5)
 *   RESET=GPIO156 (GPIO_19_4)
 *   ENABLE=GPIO61 (GPIO_7_5)
 *   iomux block "block_ts"
 *   RESET low 20ms -> INT high for 0x14 -> 2ms -> RESET high
 *   -> 6ms -> RESET input -> INT low 50ms -> INT input
 *   -> write 0x8041 = 0xAA.
 *
 * Unlike V4.13 this driver does not poll forever waiting for a controller
 * that was never bootstrapped. Probe initializes the real hardware first,
 * then performs bounded product-ID reads. Polling after successful probe is
 * only for touch-event acquisition.
 */
#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/i2c.h>
#include <linux/input.h>
#include <linux/delay.h>
#include <linux/slab.h>
#include <linux/workqueue.h>
#include <linux/gpio.h>
#include <linux/err.h>
#include <linux/mux.h>

#define HWT101_GTP_INT_GPIO       157
#define HWT101_GTP_RESET_GPIO     156
#define HWT101_GTP_ENABLE_GPIO     61

#define HWT101_GTP_REG_PRODUCT_ID 0x8140
#define HWT101_GTP_REG_STATUS     0x814e
#define HWT101_GTP_REG_POSTRESET  0x8041

#define HWT101_GTP_MAX_TOUCH      5
#define HWT101_GTP_X_MAX          1280
#define HWT101_GTP_Y_MAX          800
#define HWT101_GTP_POLL_MS        20
#define HWT101_GTP_ID_TRIES       5

struct hwt101_goodix {
    struct i2c_client *client;
    struct input_dev *input;
    struct delayed_work work;
    struct iomux_block *gpio_block;
    struct block_config *gpio_block_config;
    int stopped;
    int int_requested;
    int reset_requested;
    int enable_requested;
};

static int hwt101_gtp_read_once(struct i2c_client *client, u16 reg,
                                u8 *data, int len)
{
    u8 addr[2] = { reg >> 8, reg & 0xff };
    struct i2c_msg msg[2];
    int ret;

    msg[0].addr = client->addr;
    msg[0].flags = 0;
    msg[0].len = 2;
    msg[0].buf = addr;

    msg[1].addr = client->addr;
    msg[1].flags = I2C_M_RD;
    msg[1].len = len;
    msg[1].buf = data;

    ret = i2c_transfer(client->adapter, msg, 2);
    return ret == 2 ? 0 : (ret < 0 ? ret : -EIO);
}

static int hwt101_gtp_read_bounded(struct i2c_client *client, u16 reg,
                                   u8 *data, int len)
{
    int i, ret = -EIO;

    for (i = 0; i < HWT101_GTP_ID_TRIES; i++) {
        ret = hwt101_gtp_read_once(client, reg, data, len);
        if (!ret)
            return 0;
        msleep(20);
    }
    return ret;
}

static int hwt101_gtp_write_u8(struct i2c_client *client, u16 reg, u8 val)
{
    u8 buf[3] = { reg >> 8, reg & 0xff, val };
    struct i2c_msg msg = {
        .addr = client->addr,
        .flags = 0,
        .len = sizeof(buf),
        .buf = buf,
    };
    int ret = i2c_transfer(client->adapter, &msg, 1);

    return ret == 1 ? 0 : (ret < 0 ? ret : -EIO);
}

static void hwt101_gtp_int_sync(unsigned int ms)
{
    gpio_direction_output(HWT101_GTP_INT_GPIO, 0);
    msleep(ms);
    gpio_direction_input(HWT101_GTP_INT_GPIO);
}

static int hwt101_gtp_reset(struct i2c_client *client)
{
    int ret;

    ret = gpio_direction_output(HWT101_GTP_RESET_GPIO, 0);
    if (ret)
        return ret;

    msleep(20);

    /* FIX10/GT9xx address strap: high selects 7-bit address 0x14. */
    ret = gpio_direction_output(HWT101_GTP_INT_GPIO,
                                client->addr == 0x14 ? 1 : 0);
    if (ret)
        return ret;

    msleep(2);

    ret = gpio_direction_output(HWT101_GTP_RESET_GPIO, 1);
    if (ret)
        return ret;

    msleep(6);
    gpio_direction_input(HWT101_GTP_RESET_GPIO);

    hwt101_gtp_int_sync(50);
    gpio_direction_input(HWT101_GTP_INT_GPIO);

    /* Exact post-reset FIX10 write recovered from gtp_reset_guitar(). */
    ret = hwt101_gtp_write_u8(client, HWT101_GTP_REG_POSTRESET, 0xaa);
    if (ret)
        dev_warn(&client->dev,
                 "HWT101_GTP post-reset 0x8041=0xaa ret=%d\n", ret);

    return 0;
}

static int hwt101_gtp_hw_init(struct hwt101_goodix *ts)
{
    int ret;

    ts->gpio_block = iomux_get_block("block_ts");
    ts->gpio_block_config = iomux_get_blockconfig("block_ts");

    if (!IS_ERR(ts->gpio_block) && !IS_ERR(ts->gpio_block_config)) {
        ret = blockmux_set(ts->gpio_block, ts->gpio_block_config, NORMAL);
        if (ret)
            dev_warn(&ts->client->dev,
                     "HWT101_GTP block_ts NORMAL failed ret=%d; FIX10 continues\n",
                     ret);
    } else {
        dev_warn(&ts->client->dev,
                 "HWT101_GTP block_ts lookup failed; FIX10 continues\n");
    }

    ret = gpio_request(HWT101_GTP_ENABLE_GPIO, "gtp_enable");
    if (ret) {
        dev_err(&ts->client->dev,
                "HWT101_GTP request ENABLE gpio=%d ret=%d\n",
                HWT101_GTP_ENABLE_GPIO, ret);
        return ret;
    }
    ts->enable_requested = 1;

    ret = gpio_direction_output(HWT101_GTP_ENABLE_GPIO, 1);
    if (ret) {
        dev_err(&ts->client->dev,
                "HWT101_GTP ENABLE gpio=%d ret=%d\n",
                HWT101_GTP_ENABLE_GPIO, ret);
        return ret;
    }
    msleep(2);

    ret = gpio_request(HWT101_GTP_INT_GPIO, "gtp_int");
    if (ret) {
        dev_err(&ts->client->dev,
                "HWT101_GTP request INT gpio=%d ret=%d\n",
                HWT101_GTP_INT_GPIO, ret);
        return ret;
    }
    ts->int_requested = 1;

    ret = gpio_request(HWT101_GTP_RESET_GPIO, "gtp_reset");
    if (ret) {
        dev_err(&ts->client->dev,
                "HWT101_GTP request RESET gpio=%d ret=%d\n",
                HWT101_GTP_RESET_GPIO, ret);
        return ret;
    }
    ts->reset_requested = 1;

    ret = hwt101_gtp_reset(ts->client);
    if (ret) {
        dev_err(&ts->client->dev,
                "HWT101_GTP FIX10 reset/bootstrap failed ret=%d\n", ret);
        return ret;
    }

    dev_info(&ts->client->dev,
             "HWT101_GTP FIX10 bootstrap OK INT=%d RESET=%d ENABLE=%d addr=0x%02x\n",
             HWT101_GTP_INT_GPIO, HWT101_GTP_RESET_GPIO,
             HWT101_GTP_ENABLE_GPIO, ts->client->addr);
    return 0;
}

static void hwt101_gtp_hw_release(struct hwt101_goodix *ts)
{
    if (ts->reset_requested) {
        gpio_free(HWT101_GTP_RESET_GPIO);
        ts->reset_requested = 0;
    }
    if (ts->int_requested) {
        gpio_free(HWT101_GTP_INT_GPIO);
        ts->int_requested = 0;
    }
    if (ts->enable_requested) {
        gpio_free(HWT101_GTP_ENABLE_GPIO);
        ts->enable_requested = 0;
    }
}

static int hwt101_gtp_test(struct hwt101_goodix *ts)
{
    u8 id[4] = {0};
    int ret;

    ret = hwt101_gtp_read_bounded(ts->client, HWT101_GTP_REG_PRODUCT_ID,
                                  id, sizeof(id));
    if (ret)
        return ret;

    if (!id[0] && !id[1] && !id[2] && !id[3])
        return -ENODEV;

    dev_info(&ts->client->dev,
             "HWT101_GTP ONLINE product=%c%c%c%c bus=%d addr=0x%02x\n",
             id[0] ? id[0] : '?', id[1] ? id[1] : '?',
             id[2] ? id[2] : '?', id[3] ? id[3] : '?',
             i2c_adapter_id(ts->client->adapter), ts->client->addr);
    return 0;
}

static void goodix_ts_work_func(struct work_struct *work)
{
    struct hwt101_goodix *ts =
        container_of(to_delayed_work(work), struct hwt101_goodix, work);
    u8 status = 0, points[HWT101_GTP_MAX_TOUCH * 8];
    int n, i, ret;

    if (ts->stopped)
        return;

    ret = hwt101_gtp_read_once(ts->client, HWT101_GTP_REG_STATUS,
                               &status, 1);
    if (ret) {
        /* V4.14: no event-read printk loop on this 3.0.8 kernel. */
        goto again;
    }

    if (!(status & 0x80))
        goto again;

    n = status & 0x0f;
    if (n > HWT101_GTP_MAX_TOUCH)
        n = HWT101_GTP_MAX_TOUCH;

    if (n) {
        ret = hwt101_gtp_read_once(ts->client,
                                   HWT101_GTP_REG_STATUS + 1,
                                   points, n * 8);
        if (ret)
            goto clear;

        for (i = 0; i < n; i++) {
            u8 *p = &points[i * 8];
            int x = p[1] | (p[2] << 8);
            int y = p[3] | (p[4] << 8);
            int w = p[5] | (p[6] << 8);

            if (x > HWT101_GTP_X_MAX)
                x = HWT101_GTP_X_MAX;
            if (y > HWT101_GTP_Y_MAX)
                y = HWT101_GTP_Y_MAX;
            if (w < 1)
                w = 1;
            if (w > 255)
                w = 255;

            input_report_abs(ts->input, ABS_MT_TOUCH_MAJOR, w);
            input_report_abs(ts->input, ABS_MT_POSITION_X, x);
            input_report_abs(ts->input, ABS_MT_POSITION_Y, y);
            input_mt_sync(ts->input);
        }
    } else {
        input_mt_sync(ts->input);
    }
    input_sync(ts->input);

clear:
    hwt101_gtp_write_u8(ts->client, HWT101_GTP_REG_STATUS, 0);
again:
    if (!ts->stopped)
        schedule_delayed_work(&ts->work,
                              msecs_to_jiffies(HWT101_GTP_POLL_MS));
}

static int goodix_ts_probe(struct i2c_client *client,
                           const struct i2c_device_id *id)
{
    struct hwt101_goodix *ts;
    struct input_dev *input;
    int ret;

    if (!i2c_check_functionality(client->adapter, I2C_FUNC_I2C))
        return -ENODEV;

    ts = kzalloc(sizeof(*ts), GFP_KERNEL);
    if (!ts)
        return -ENOMEM;

    ts->client = client;
    i2c_set_clientdata(client, ts);

    ret = hwt101_gtp_hw_init(ts);
    if (ret)
        goto err_hw;

    ret = hwt101_gtp_test(ts);
    if (ret) {
        dev_err(&client->dev,
                "HWT101_GTP controller NACK after FIX10 bootstrap ret=%d\n",
                ret);
        goto err_hw;
    }

    input = input_allocate_device();
    if (!input) {
        ret = -ENOMEM;
        goto err_hw;
    }

    ts->input = input;
    INIT_DELAYED_WORK(&ts->work, goodix_ts_work_func);

    input->name = "goodix-ts";
    input->id.bustype = BUS_I2C;
    input->dev.parent = &client->dev;
    set_bit(EV_ABS, input->evbit);
    input_set_abs_params(input, ABS_MT_POSITION_X,
                         0, HWT101_GTP_X_MAX, 0, 0);
    input_set_abs_params(input, ABS_MT_POSITION_Y,
                         0, HWT101_GTP_Y_MAX, 0, 0);
    input_set_abs_params(input, ABS_MT_TOUCH_MAJOR, 0, 255, 0, 0);

    ret = input_register_device(input);
    if (ret) {
        input_free_device(input);
        ts->input = NULL;
        goto err_hw;
    }

    dev_info(&client->dev,
             "HWT101_GTP input goodix-ts registered after verified ACK\n");

    schedule_delayed_work(&ts->work,
                          msecs_to_jiffies(HWT101_GTP_POLL_MS));
    return 0;

err_hw:
    hwt101_gtp_hw_release(ts);
    i2c_set_clientdata(client, NULL);
    kfree(ts);
    return ret;
}

static int goodix_ts_remove(struct i2c_client *client)
{
    struct hwt101_goodix *ts = i2c_get_clientdata(client);

    if (!ts)
        return 0;

    ts->stopped = 1;
    if (ts->input) {
        cancel_delayed_work_sync(&ts->work);
        input_unregister_device(ts->input);
    }

    hwt101_gtp_hw_release(ts);
    i2c_set_clientdata(client, NULL);
    kfree(ts);
    return 0;
}

static const struct i2c_device_id goodix_ts_id[] = {
    { "Goodix-TS", 0 },
    { "goodix-ts", 0 },
    { "gt9xx", 0 },
    { }
};
MODULE_DEVICE_TABLE(i2c, goodix_ts_id);

static struct i2c_driver goodix_ts_driver = {
    .driver = {
        .name = "Goodix-TS",
        .owner = THIS_MODULE,
    },
    .probe = goodix_ts_probe,
    .remove = goodix_ts_remove,
    .id_table = goodix_ts_id,
};

static int __init hwt101_goodix_init(void)
{
    printk(KERN_INFO
           "HWT101_GTP: V4.14 FIX10 bootstrap INT=157 RESET=156 ENABLE=61\n");
    return i2c_add_driver(&goodix_ts_driver);
}
late_initcall(hwt101_goodix_init);

static void __exit hwt101_goodix_exit(void)
{
    i2c_del_driver(&goodix_ts_driver);
}
module_exit(hwt101_goodix_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("HWT101 Goodix GT9280 FIX10 bootstrap parity V4.14");
'''
g.write_text(src)

# ------------------------------------------------------------------
# 3) LOGGER: bounded diagnostics only. Do NOT enable CONFIG_K3_LOG yet.
# ------------------------------------------------------------------
logf = root / "drivers/staging/android/logger.c"
s = logf.read_text()

counter_anchor = "static int logctl_nv = 0;\n"
if counter_anchor not in s:
    raise SystemExit("logger counter anchor missing")
s = s.replace(counter_anchor, counter_anchor + '''
/* HWT101 V4.14 bounded logger diagnostics. */
static int hwt101_logger_open_diag;
static int hwt101_logger_write_diag;
static int hwt101_logger_written_diag;
static int hwt101_logger_ioctl_diag;
''', 1)

open_anchor = '''\tlog = get_log_from_minor(MINOR(inode->i_rdev));
\tif (!log)
\t\treturn -ENODEV;
'''
if open_anchor not in s:
    raise SystemExit("logger_open anchor missing")
s = s.replace(open_anchor, open_anchor + '''
\tif (hwt101_logger_open_diag < 20) {
\t\tprintk(KERN_INFO
\t\t       "HWT101_LOGGER OPEN name=%s minor=%d mode=0x%x w_off=%lu head=%lu size=%lu\\n",
\t\t       log->misc.name, log->misc.minor, file->f_mode,
\t\t       (unsigned long)log->w_off, (unsigned long)log->head,
\t\t       (unsigned long)log->size);
\t\thwt101_logger_open_diag++;
\t}
''', 1)

write_anchor = '''\theader.len = min_t(size_t, iocb->ki_left, LOGGER_ENTRY_MAX_PAYLOAD);

\t/* null writes succeed, return zero */
'''
if write_anchor not in s:
    raise SystemExit("logger write header anchor missing")
s = s.replace(write_anchor, '''\theader.len = min_t(size_t, iocb->ki_left, LOGGER_ENTRY_MAX_PAYLOAD);

\tif (hwt101_logger_write_diag < 20) {
\t\tprintk(KERN_INFO
\t\t       "HWT101_LOGGER WRITE name=%s minor=%d segs=%lu len=%u w_off=%lu head=%lu\\n",
\t\t       log->misc.name, log->misc.minor, nr_segs, header.len,
\t\t       (unsigned long)log->w_off, (unsigned long)log->head);
\t\thwt101_logger_write_diag++;
\t}

\t/* null writes succeed, return zero */
''', 1)

written_anchor = '''\tmutex_unlock(&log->mutex);

\t/* wake up any blocked readers */
'''
if written_anchor not in s:
    raise SystemExit("logger written anchor missing")
s = s.replace(written_anchor, '''\tif (hwt101_logger_written_diag < 20) {
\t\tprintk(KERN_INFO
\t\t       "HWT101_LOGGER WROTE name=%s ret=%ld w_off=%lu head=%lu\\n",
\t\t       log->misc.name, (long)ret,
\t\t       (unsigned long)log->w_off, (unsigned long)log->head);
\t\thwt101_logger_written_diag++;
\t}

\tmutex_unlock(&log->mutex);

\t/* wake up any blocked readers */
''', 1)

ioctl_anchor = '''\tmutex_unlock(&log->mutex);

\treturn ret;
}

static const struct file_operations logger_fops = {
'''
if ioctl_anchor not in s:
    raise SystemExit("logger ioctl anchor missing")
s = s.replace(ioctl_anchor, '''\tif (hwt101_logger_ioctl_diag < 20) {
\t\tprintk(KERN_INFO
\t\t       "HWT101_LOGGER IOCTL name=%s cmd=0x%x ret=%ld w_off=%lu head=%lu\\n",
\t\t       log->misc.name, cmd, ret,
\t\t       (unsigned long)log->w_off, (unsigned long)log->head);
\t\thwt101_logger_ioctl_diag++;
\t}

\tmutex_unlock(&log->mutex);

\treturn ret;
}

static const struct file_operations logger_fops = {
''', 1)

logf.write_text(s)

# ------------------------------------------------------------------
# Gates: this patch must remain narrowly scoped.
# ------------------------------------------------------------------
gs = g.read_text()
for tok in (
    "HWT101_GTP_INT_GPIO       157",
    "HWT101_GTP_RESET_GPIO     156",
    "HWT101_GTP_ENABLE_GPIO     61",
    'iomux_get_block("block_ts")',
    "client->addr == 0x14 ? 1 : 0",
    "HWT101_GTP_REG_POSTRESET  0x8041",
    "0xaa",
    "controller NACK after FIX10 bootstrap",
):
    if tok not in gs:
        raise SystemExit("Goodix gate failed: " + tok)

if "asynchronous controller retry enabled" in gs or "HWT101_GTP waiting for controller" in gs:
    raise SystemExit("V4.13 infinite retry path still present")

ps = panel.read_text()
for pat in (
    r'pinfo->xres\s*=\s*1280\s*;',
    r'pinfo->yres\s*=\s*800\s*;',
    r'pinfo->width\s*=\s*230\s*;',
    r'pinfo->height\s*=\s*149\s*;',
    r'pinfo->ldi\.h_back_porch\s*=\s*60\s*;',
    r'pinfo->ldi\.h_front_porch\s*=\s*70\s*;',
    r'pinfo->ldi\.h_pulse_width\s*=\s*60\s*;',
    r'pinfo->ldi\.v_back_porch\s*=\s*13\s*;',
    r'pinfo->ldi\.v_front_porch\s*=\s*13\s*;',
    r'pinfo->ldi\.v_pulse_width\s*=\s*7\s*;',
    r'pinfo->mipi\.dsi_bit_clk\s*=\s*228\s*;',
):
    if not re.search(pat, ps):
        raise SystemExit("display gate failed: " + pat)

ls = logf.read_text()
for tok in (
    "HWT101_LOGGER OPEN",
    "HWT101_LOGGER WRITE",
    "HWT101_LOGGER WROTE",
    "HWT101_LOGGER IOCTL",
):
    if tok not in ls:
        raise SystemExit("logger diagnostic gate failed: " + tok)

print("V414_PATCH=PASS")
print("TOUCH=FIX10_GPIO_IOMUX_RESET_ADDR_STRAP")
print("TOUCH_INT_GPIO=157")
print("TOUCH_RESET_GPIO=156")
print("TOUCH_ENABLE_GPIO=61")
print("TOUCH_POSTRESET=0x8041_AA")
print("TOUCH_INFINITE_NACK_RETRY=REMOVED")
print("DISPLAY_H_TIMING=60_70_60")
print("DISPLAY_V_TIMING=13_13_7")
print("DISPLAY_DSI_BIT_CLK=228")
print("DISPLAY_PIXEL_CLK=76000000_UNCHANGED")
print("DISPLAY_SN65_TABLE=UNCHANGED")
print("FRAMEBUFFER_STRIDE=UNCHANGED_FROM_V413")
print("LOGGER=BOUNDED_DIAGNOSTIC_ONLY")
print("K3_LOG=UNCHANGED_OFF")
print("BATTERY_HSAD_YAFFS_NAND=UNCHANGED")
