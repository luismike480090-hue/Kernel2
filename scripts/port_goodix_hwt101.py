#!/usr/bin/env python3
from pathlib import Path
import sys

K = Path(sys.argv[1] if len(sys.argv) > 1 else 'kernel').resolve()
D = K / 'drivers/input/touchscreen'
M = D / 'Makefile'
C = D / 'hwt101_goodix.c'

src = r'''/*
 * HWT101 Goodix GT9xx compatibility driver for Linux 3.0.x / K3V2.
 *
 * This is intentionally conservative: it uses the OEM-observed I2C bus 2,
 * address 0x14, legacy multitouch reporting, and polling instead of guessing
 * unknown HWT101 reset/IRQ GPIO numbers.  If board code already creates the
 * goodix-ts I2C device, this driver binds to it; otherwise it creates a safe
 * fallback device at 2:0x14.
 */
#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/i2c.h>
#include <linux/input.h>
#include <linux/delay.h>
#include <linux/slab.h>
#include <linux/workqueue.h>

#define HWT101_GTP_BUS              2
#define HWT101_GTP_ADDR             0x14
#define HWT101_GTP_REG_PRODUCT_ID   0x8140
#define HWT101_GTP_REG_STATUS       0x814e
#define HWT101_GTP_MAX_TOUCH        5
#define HWT101_GTP_X_MAX            1280
#define HWT101_GTP_Y_MAX            800
#define HWT101_GTP_POLL_MS          20

struct hwt101_goodix {
    struct i2c_client *client;
    struct input_dev *input;
    struct delayed_work work;
    int stopped;
};

static struct i2c_client *hwt101_created_client;

static int hwt101_gtp_read(struct i2c_client *client, u16 reg, u8 *data, int len)
{
    u8 addr[2];
    struct i2c_msg msg[2];
    int ret;

    addr[0] = reg >> 8;
    addr[1] = reg & 0xff;

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

static int hwt101_gtp_write_u8(struct i2c_client *client, u16 reg, u8 val)
{
    u8 buf[3];
    struct i2c_msg msg;
    int ret;

    buf[0] = reg >> 8;
    buf[1] = reg & 0xff;
    buf[2] = val;
    msg.addr = client->addr;
    msg.flags = 0;
    msg.len = sizeof(buf);
    msg.buf = buf;
    ret = i2c_transfer(client->adapter, &msg, 1);
    return ret == 1 ? 0 : (ret < 0 ? ret : -EIO);
}

/* OEM symbol/call-map anchors retained for parity auditing. */
static int gtp_request_io_port(struct i2c_client *client)
{
    dev_info(&client->dev,
             "HWT101 Goodix: polling mode, preserving unknown OEM GPIO/IOMUX\n");
    return 0;
}

static int gtp_i2c_test(struct i2c_client *client)
{
    u8 id[4] = { 0, 0, 0, 0 };
    int ret = hwt101_gtp_read(client, HWT101_GTP_REG_PRODUCT_ID, id, sizeof(id));
    if (ret)
        return ret;
    dev_info(&client->dev, "HWT101 Goodix product id: %c%c%c%c\n",
             id[0] ? id[0] : '?', id[1] ? id[1] : '?',
             id[2] ? id[2] : '?', id[3] ? id[3] : '?');
    return 0;
}

static void goodix_ts_work_func(struct work_struct *work)
{
    struct hwt101_goodix *ts = container_of(to_delayed_work(work),
                                             struct hwt101_goodix, work);
    u8 status = 0;
    u8 points[HWT101_GTP_MAX_TOUCH * 8];
    int n, i, ret;

    if (ts->stopped)
        return;

    ret = hwt101_gtp_read(ts->client, HWT101_GTP_REG_STATUS, &status, 1);
    if (ret)
        goto again;

    if (!(status & 0x80))
        goto again;

    n = status & 0x0f;
    if (n > HWT101_GTP_MAX_TOUCH)
        n = HWT101_GTP_MAX_TOUCH;

    if (n) {
        ret = hwt101_gtp_read(ts->client, HWT101_GTP_REG_STATUS + 1,
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
        schedule_delayed_work(&ts->work, msecs_to_jiffies(HWT101_GTP_POLL_MS));
}

static int goodix_ts_probe(struct i2c_client *client,
                           const struct i2c_device_id *id)
{
    struct hwt101_goodix *ts;
    struct input_dev *input;
    int ret;

    if (!i2c_check_functionality(client->adapter, I2C_FUNC_I2C))
        return -ENODEV;

    ret = gtp_request_io_port(client);
    if (ret)
        return ret;

    ret = gtp_i2c_test(client);
    if (ret) {
        dev_err(&client->dev, "HWT101 Goodix not responding at bus %d addr 0x%02x: %d\n",
                i2c_adapter_id(client->adapter), client->addr, ret);
        return ret;
    }

    ts = kzalloc(sizeof(*ts), GFP_KERNEL);
    if (!ts)
        return -ENOMEM;

    input = input_allocate_device();
    if (!input) {
        kfree(ts);
        return -ENOMEM;
    }

    ts->client = client;
    ts->input = input;
    INIT_DELAYED_WORK(&ts->work, goodix_ts_work_func);
    i2c_set_clientdata(client, ts);

    input->name = "goodix-ts";
    input->id.bustype = BUS_I2C;
    input->dev.parent = &client->dev;
    set_bit(EV_ABS, input->evbit);
    input_set_abs_params(input, ABS_MT_POSITION_X, 0, HWT101_GTP_X_MAX, 0, 0);
    input_set_abs_params(input, ABS_MT_POSITION_Y, 0, HWT101_GTP_Y_MAX, 0, 0);
    input_set_abs_params(input, ABS_MT_TOUCH_MAJOR, 0, 255, 0, 0);

    ret = input_register_device(input);
    if (ret) {
        input_free_device(input);
        kfree(ts);
        i2c_set_clientdata(client, NULL);
        return ret;
    }

    dev_info(&client->dev,
             "HWT101 Goodix active: bus=%d addr=0x%02x poll=%dms range=%dx%d\n",
             i2c_adapter_id(client->adapter), client->addr,
             HWT101_GTP_POLL_MS, HWT101_GTP_X_MAX, HWT101_GTP_Y_MAX);

    schedule_delayed_work(&ts->work, msecs_to_jiffies(HWT101_GTP_POLL_MS));
    return 0;
}

static int goodix_ts_remove(struct i2c_client *client)
{
    struct hwt101_goodix *ts = i2c_get_clientdata(client);
    if (!ts)
        return 0;
    ts->stopped = 1;
    cancel_delayed_work_sync(&ts->work);
    input_unregister_device(ts->input);
    i2c_set_clientdata(client, NULL);
    kfree(ts);
    return 0;
}

static const struct i2c_device_id goodix_ts_id[] = {
    { "goodix-ts", 0 },
    { "gt9xx", 0 },
    { }
};
MODULE_DEVICE_TABLE(i2c, goodix_ts_id);

static struct i2c_driver goodix_ts_driver = {
    .driver = {
        .name = "goodix-ts",
        .owner = THIS_MODULE,
    },
    .probe = goodix_ts_probe,
    .remove = goodix_ts_remove,
    .id_table = goodix_ts_id,
};

static int __init hwt101_goodix_init(void)
{
    struct i2c_adapter *adap;
    struct i2c_board_info info = {
        I2C_BOARD_INFO("goodix-ts", HWT101_GTP_ADDR),
    };
    int ret;

    ret = i2c_add_driver(&goodix_ts_driver);
    if (ret)
        return ret;

    adap = i2c_get_adapter(HWT101_GTP_BUS);
    if (!adap) {
        pr_warn("HWT101 Goodix: I2C bus %d unavailable; waiting for board-created device\n",
                HWT101_GTP_BUS);
        return 0;
    }

    hwt101_created_client = i2c_new_device(adap, &info);
    i2c_put_adapter(adap);
    if (!hwt101_created_client)
        pr_info("HWT101 Goodix: bus 2 addr 0x14 already occupied or board-owned\n");
    else
        pr_info("HWT101 Goodix: fallback device created at bus 2 addr 0x14\n");
    return 0;
}
late_initcall(hwt101_goodix_init);

static void __exit hwt101_goodix_exit(void)
{
    if (hwt101_created_client)
        i2c_unregister_device(hwt101_created_client);
    i2c_del_driver(&goodix_ts_driver);
}
module_exit(hwt101_goodix_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("HWT101 Goodix GT9xx K3V2 compatibility driver");
'''

D.mkdir(parents=True, exist_ok=True)
C.write_text(src)
print('PATCHED', C.relative_to(K))

t = M.read_text(errors='ignore')
line = 'obj-y += hwt101_goodix.o  # HWT101 Goodix active touchscreen\n'
if 'hwt101_goodix.o' not in t:
    if not t.endswith('\n'):
        t += '\n'
    t += line
    M.write_text(t)
    print('PATCHED', M.relative_to(K))
else:
    print('GOODIX Makefile entry already present')

report = Path('HWT101-GOODIX-PORT.txt')
report.write_text('''HWT101 Goodix V3.28\nsource strategy: HWT101-specific Linux 3.0-compatible driver using public GT9xx protocol behavior\nOEM anchors retained: goodix_ts_probe, goodix_ts_work_func, gtp_request_io_port, gtp_i2c_test\nactive controller evidence: I2C bus 2 address 0x14\nmode: polling 20 ms; unknown OEM IRQ/reset GPIO numbers are deliberately not guessed\ninput range: 1280x800 legacy multitouch\nfallback registration: creates goodix-ts at bus 2 addr 0x14 only when address is not already board-owned\nstatus: compile/runtime candidate; not yet declared final until device boot validation\n''')
print(report.read_text())
