#!/usr/bin/env python3
from pathlib import Path
import re, sys

root=Path(sys.argv[1] if len(sys.argv)>1 else "kernel")

# 1) Framebuffer parity: FIX10 uses 5120-byte stride at 1280x32bpp.
fbh=root/"drivers/video/k3/k3_fb.h"
s=fbh.read_text()
old="#define CONFIG_FB_STRIDE_64BYTES_ODD_ALIGN\t1"
if old not in s:
    raise SystemExit("stride define anchor missing")
s=s.replace(old,"/* HWT101 FIX10: no odd 64-byte stride padding */",1)
fbh.write_text(s)

# 2) Keep NAND write guard, silence only ALLOW spam.
nand=root/"drivers/mtd/nand/hinand_hwt101.c"
s=nand.read_text()
before=s
s=re.sub(r'^.*HWT101_V405_ANDROID_GUARD: ALLOW PAGEPROG.*\n','',s,flags=re.M)
s=re.sub(r'^.*HWT101_V405_ANDROID_GUARD: ALLOW ERASE2.*\n','',s,flags=re.M)
if s==before:
    raise SystemExit("NAND ALLOW printk anchors missing")
if "HWT101_V405_ANDROID_GUARD: BLOCK PAGEPROG" not in s or "HWT101_V405_ANDROID_GUARD: BLOCK ERASE2" not in s:
    raise SystemExit("NAND BLOCK guard missing")
nand.write_text(s)

# 3) Android logger: Huawei NV gating can leave userspace log buffers empty.
# Preserve logger devices/ABI, but accept all writes like standard Android logger.
logf=root/"drivers/staging/android/logger.c"
s=logf.read_text()
pat=re.compile(r'''\s*if \(logctl_nv == 1 \|\| minor_of_events == log->misc.minor\s*
\s*\|\| \(\(minor_of_main == log->misc.minor\) && \(priority >= ANDROID_LOG_INFO\)\)\s*
\s*\|\|minor_of_power == log->misc.minor\)\s*
\s*\{\s*
\s*/\* log it \*/\s*
\s*\}\s*
\s*else\s*
\s*\{\s*
\s*return 0;\s*
\s*\}''',re.X)
replacement='''
        /* HWT101: keep the Android logger writable regardless of Huawei
         * logctl NV state. The FIX10 userspace expects /dev/log/* to receive
         * main/system/radio/events continuously. */
'''
s,n=pat.subn(replacement,s,count=1)
if n!=1:
    raise SystemExit("logger NV filter anchor missing")
logf.write_text(s)

# 4) Goodix GT9280: do not permanently fail if the controller is not ready
# at late_initcall. FIX10 installs the driver ~12.7s and registers input only
# around ~15.8s. Register the input immediately and retry I2C until it responds.
g=root/"drivers/input/touchscreen/hwt101_goodix.c"
if not g.exists():
    raise SystemExit("V412 Goodix source missing")
src=r'''/*
 * HWT101 Goodix GT9280 compatibility driver V4.13.
 * FIX10 topology: I2C2 @ 0x14, product 9280_1040, input name goodix-ts.
 *
 * Important: the OEM driver may need several seconds before the controller
 * is readable. Therefore probe never permanently aborts on the first I2C
 * miss; it registers the input node and retries until GT9280 answers.
 */
#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/i2c.h>
#include <linux/input.h>
#include <linux/delay.h>
#include <linux/slab.h>
#include <linux/workqueue.h>

#define HWT101_GTP_REG_PRODUCT_ID 0x8140
#define HWT101_GTP_REG_STATUS     0x814e
#define HWT101_GTP_MAX_TOUCH      5
#define HWT101_GTP_X_MAX          1280
#define HWT101_GTP_Y_MAX          800
#define HWT101_GTP_POLL_MS        20
#define HWT101_GTP_RETRY_MS       250

struct hwt101_goodix {
    struct i2c_client *client;
    struct input_dev *input;
    struct delayed_work work;
    int stopped;
    int online;
    int fail_count;
};

static int hwt101_gtp_read(struct i2c_client *client, u16 reg, u8 *data, int len)
{
    u8 addr[2] = { reg >> 8, reg & 0xff };
    struct i2c_msg msg[2];
    int ret;
    msg[0].addr=client->addr; msg[0].flags=0; msg[0].len=2; msg[0].buf=addr;
    msg[1].addr=client->addr; msg[1].flags=I2C_M_RD; msg[1].len=len; msg[1].buf=data;
    ret=i2c_transfer(client->adapter,msg,2);
    return ret==2 ? 0 : (ret<0 ? ret : -EIO);
}

static int hwt101_gtp_write_u8(struct i2c_client *client, u16 reg, u8 val)
{
    u8 buf[3] = { reg >> 8, reg & 0xff, val };
    struct i2c_msg msg = { .addr=client->addr, .flags=0, .len=3, .buf=buf };
    int ret=i2c_transfer(client->adapter,&msg,1);
    return ret==1 ? 0 : (ret<0 ? ret : -EIO);
}

static int hwt101_gtp_test(struct hwt101_goodix *ts)
{
    u8 id[4]={0};
    int ret=hwt101_gtp_read(ts->client,HWT101_GTP_REG_PRODUCT_ID,id,sizeof(id));
    if (ret) return ret;
    if (!id[0] && !id[1] && !id[2] && !id[3]) return -ENODEV;
    if (!ts->online)
        dev_info(&ts->client->dev,
          "HWT101_GTP ONLINE product=%c%c%c%c bus=%d addr=0x%02x\n",
          id[0]?id[0]:'?',id[1]?id[1]:'?',id[2]?id[2]:'?',id[3]?id[3]:'?',
          i2c_adapter_id(ts->client->adapter),ts->client->addr);
    ts->online=1;
    ts->fail_count=0;
    return 0;
}

static void goodix_ts_work_func(struct work_struct *work)
{
    struct hwt101_goodix *ts=
        container_of(to_delayed_work(work),struct hwt101_goodix,work);
    u8 status=0, points[HWT101_GTP_MAX_TOUCH*8];
    int n,i,ret,delay=HWT101_GTP_POLL_MS;

    if (ts->stopped) return;

    if (!ts->online) {
        ret=hwt101_gtp_test(ts);
        if (ret) {
            if ((ts->fail_count++ % 20)==0)
                dev_warn(&ts->client->dev,
                  "HWT101_GTP waiting for controller ret=%d try=%d\n",
                  ret,ts->fail_count);
            delay=HWT101_GTP_RETRY_MS;
            goto again;
        }
    }

    ret=hwt101_gtp_read(ts->client,HWT101_GTP_REG_STATUS,&status,1);
    if (ret) {
        if (++ts->fail_count >= 10) {
            ts->online=0;
            dev_warn(&ts->client->dev,
              "HWT101_GTP lost controller, retrying\n");
        }
        delay=HWT101_GTP_RETRY_MS;
        goto again;
    }
    ts->fail_count=0;

    if (!(status & 0x80))
        goto again;

    n=status & 0x0f;
    if (n>HWT101_GTP_MAX_TOUCH) n=HWT101_GTP_MAX_TOUCH;

    if (n) {
        ret=hwt101_gtp_read(ts->client,HWT101_GTP_REG_STATUS+1,points,n*8);
        if (ret) goto clear;
        for (i=0;i<n;i++) {
            u8 *p=&points[i*8];
            int x=p[1] | (p[2]<<8);
            int y=p[3] | (p[4]<<8);
            int w=p[5] | (p[6]<<8);
            if (x>HWT101_GTP_X_MAX) x=HWT101_GTP_X_MAX;
            if (y>HWT101_GTP_Y_MAX) y=HWT101_GTP_Y_MAX;
            if (w<1) w=1; if (w>255) w=255;
            input_report_abs(ts->input,ABS_MT_TOUCH_MAJOR,w);
            input_report_abs(ts->input,ABS_MT_POSITION_X,x);
            input_report_abs(ts->input,ABS_MT_POSITION_Y,y);
            input_mt_sync(ts->input);
        }
    } else {
        input_mt_sync(ts->input);
    }
    input_sync(ts->input);

clear:
    hwt101_gtp_write_u8(ts->client,HWT101_GTP_REG_STATUS,0);
again:
    if (!ts->stopped)
        schedule_delayed_work(&ts->work,msecs_to_jiffies(delay));
}

static int goodix_ts_probe(struct i2c_client *client,
                           const struct i2c_device_id *id)
{
    struct hwt101_goodix *ts;
    struct input_dev *input;
    int ret;

    if (!i2c_check_functionality(client->adapter,I2C_FUNC_I2C))
        return -ENODEV;

    ts=kzalloc(sizeof(*ts),GFP_KERNEL);
    if (!ts) return -ENOMEM;
    input=input_allocate_device();
    if (!input) { kfree(ts); return -ENOMEM; }

    ts->client=client; ts->input=input;
    INIT_DELAYED_WORK(&ts->work,goodix_ts_work_func);
    i2c_set_clientdata(client,ts);

    input->name="goodix-ts";
    input->id.bustype=BUS_I2C;
    input->dev.parent=&client->dev;
    set_bit(EV_ABS,input->evbit);
    input_set_abs_params(input,ABS_MT_POSITION_X,0,HWT101_GTP_X_MAX,0,0);
    input_set_abs_params(input,ABS_MT_POSITION_Y,0,HWT101_GTP_Y_MAX,0,0);
    input_set_abs_params(input,ABS_MT_TOUCH_MAJOR,0,255,0,0);

    ret=input_register_device(input);
    if (ret) {
        input_free_device(input); kfree(ts);
        i2c_set_clientdata(client,NULL);
        return ret;
    }

    dev_info(&client->dev,
      "HWT101_GTP input registered; asynchronous controller retry enabled\n");

    ret=hwt101_gtp_test(ts);
    if (ret)
        dev_warn(&client->dev,
          "HWT101_GTP initial read pending ret=%d; will retry\n",ret);

    schedule_delayed_work(&ts->work,msecs_to_jiffies(HWT101_GTP_RETRY_MS));
    return 0;
}

static int goodix_ts_remove(struct i2c_client *client)
{
    struct hwt101_goodix *ts=i2c_get_clientdata(client);
    if (!ts) return 0;
    ts->stopped=1;
    cancel_delayed_work_sync(&ts->work);
    input_unregister_device(ts->input);
    i2c_set_clientdata(client,NULL);
    kfree(ts);
    return 0;
}

static const struct i2c_device_id goodix_ts_id[] = {
    { "Goodix-TS", 0 }, { "goodix-ts", 0 }, { "gt9xx", 0 }, { }
};
MODULE_DEVICE_TABLE(i2c,goodix_ts_id);

static struct i2c_driver goodix_ts_driver = {
    .driver={ .name="Goodix-TS", .owner=THIS_MODULE },
    .probe=goodix_ts_probe,
    .remove=goodix_ts_remove,
    .id_table=goodix_ts_id,
};

static int __init hwt101_goodix_init(void)
{
    printk(KERN_INFO "HWT101_GTP: V4.13 install/retry driver\n");
    return i2c_add_driver(&goodix_ts_driver);
}
late_initcall(hwt101_goodix_init);

static void __exit hwt101_goodix_exit(void)
{
    i2c_del_driver(&goodix_ts_driver);
}
module_exit(hwt101_goodix_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("HWT101 Goodix GT9280 resilient compatibility V4.13");
'''
g.write_text(src)

# Gates
assert "CONFIG_FB_STRIDE_64BYTES_ODD_ALIGN" not in fbh.read_text()
ns=nand.read_text()
assert "ALLOW PAGEPROG" not in ns and "ALLOW ERASE2" not in ns
assert "BLOCK PAGEPROG" in ns and "BLOCK ERASE2" in ns
ls=logf.read_text()
assert "HWT101: keep the Android logger writable" in ls
assert "return 0;" in ls  # other legitimate returns remain
gs=g.read_text()
for tok in ("V4.13 install/retry driver","asynchronous controller retry enabled",
            "HWT101_GTP ONLINE","HWT101_GTP_RETRY_MS"):
    assert tok in gs

print("V413_PATCH=PASS")
print("FRAMEBUFFER_STRIDE=FIX10_5120_FORMULA")
print("GOODIX=REGISTER_INPUT_AND_RETRY")
print("LOGCAT=NV_FILTER_BYPASSED")
print("NAND_ALLOW_PRINTK=REMOVED")
print("NAND_BLOCK_GUARD=PRESERVED")
print("BATTERY_HSAD_YAFFS=UNCHANGED")
