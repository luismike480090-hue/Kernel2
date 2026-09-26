#!/usr/bin/env python3
from pathlib import Path
import re, sys

root=Path(sys.argv[1] if len(sys.argv)>1 else "kernel")

# ------------------------------------------------------------------
# 1) FIX10 display regulator parity recovered from the golden binary.
# Golden FIX10 regulator_init_data proves:
#   LDO15: lcdanalog-vcc/k3_dev_lcd + lcd-vcc/sn65dsi83
#   LDO16: lcdio-vcc/k3_dev_lcd
#   LDO17: zero consumers
#
# The public donor instead assigns wificore to LDO15 and lcdanalog to
# LDO17. Restore the OEM topology.  Add 1-002d as a compatibility alias
# because the public Linux i2c-core names the SN65 client by bus/address.
# ------------------------------------------------------------------
reg=root/"arch/arm/mach-k3v2/include/mach/board-hi6421-regulator.h"
s=reg.read_text()

old='''static struct regulator_consumer_supply ldo15_consumers[] = {
	REGULATOR_SUPPLY("wificore-vcc", "wifi-core"),
};
static struct regulator_consumer_supply ldo16_consumers[] = {
	REGULATOR_SUPPLY("lcdio-vcc", "k3_dev_lcd"),
};
static struct regulator_consumer_supply ldo17_consumers[] = {
	REGULATOR_SUPPLY("lcdanalog-vcc", "k3_dev_lcd"),
};'''
new='''static struct regulator_consumer_supply ldo15_consumers[] = {
	/* Exact FIX10 consumers recovered from golden kernel binary. */
	REGULATOR_SUPPLY("lcdanalog-vcc", "k3_dev_lcd"),
	REGULATOR_SUPPLY("lcd-vcc", "sn65dsi83"),
	/* Compatibility alias for the public i2c-core dev_name (bus 1, 0x2d). */
	REGULATOR_SUPPLY("lcd-vcc", "1-002d"),
};
static struct regulator_consumer_supply ldo16_consumers[] = {
	REGULATOR_SUPPLY("lcdio-vcc", "k3_dev_lcd"),
};
/* FIX10 LDO17 has zero consumer supplies. Keep a declaration for source
 * compatibility but do not register it in k3v2_regulators below. */
static struct regulator_consumer_supply ldo17_consumers[] = {
	REGULATOR_SUPPLY("hwt101-unused-ldo17", NULL),
};'''
if old not in s:
    raise SystemExit("LDO15/16/17 consumer anchor missing")
s=s.replace(old,new,1)

# Set LDO17 consumer count to zero exactly as FIX10 binary.
pat=re.compile(r'(\[HI6421_LDO17\]\s*=\s*\{.*?\.always_on\s*=\s*0,\s*\},)\s*\.num_consumer_supplies\s*=\s*ARRAY_SIZE\(ldo17_consumers\),\s*\.consumer_supplies\s*=\s*ldo17_consumers,',re.S)
repl=r'''\1
		.num_consumer_supplies = 0,
		.consumer_supplies = NULL,'''
s,n=pat.subn(repl,s,count=1)
if n!=1:
    raise SystemExit("LDO17 init-data anchor missing")
reg.write_text(s)

# ------------------------------------------------------------------
# 2) HWT101 Goodix GT9280-compatible driver.
# FIX10 facts:
#   board I2C bus 2, address 0x14
#   IC reports 9280_1040
#   input device name goodix-ts
# GPIO configuration in FIX10 itself logs a failure but touch still works.
# To avoid guessing GPIO reset sequencing, poll the real GT9xx registers.
# ------------------------------------------------------------------
td=root/"drivers/input/touchscreen"
mk=td/"Makefile"
drv=td/"hwt101_goodix.c"

src=r'''/*
 * HWT101 Goodix GT9280 compatibility driver.
 * Device topology recovered from FIX10: I2C2 @ 0x14.
 * Uses 20ms polling so functionality does not depend on unrecovered OEM
 * reset/IRQ GPIO setup. Android 4.1 legacy Type-A multitouch reporting.
 */
#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/i2c.h>
#include <linux/input.h>
#include <linux/delay.h>
#include <linux/slab.h>
#include <linux/workqueue.h>

#define HWT101_GTP_ADDR           0x14
#define HWT101_GTP_REG_PRODUCT_ID 0x8140
#define HWT101_GTP_REG_STATUS     0x814e
#define HWT101_GTP_MAX_TOUCH      5
#define HWT101_GTP_X_MAX          1280
#define HWT101_GTP_Y_MAX          800
#define HWT101_GTP_POLL_MS        20

struct hwt101_goodix {
    struct i2c_client *client;
    struct input_dev *input;
    struct delayed_work work;
    int stopped;
};

static int hwt101_gtp_read(struct i2c_client *client, u16 reg, u8 *data, int len)
{
    u8 addr[2] = { reg >> 8, reg & 0xff };
    struct i2c_msg msg[2];
    int ret;

    msg[0].addr=client->addr; msg[0].flags=0;
    msg[0].len=2; msg[0].buf=addr;
    msg[1].addr=client->addr; msg[1].flags=I2C_M_RD;
    msg[1].len=len; msg[1].buf=data;
    ret=i2c_transfer(client->adapter,msg,2);
    return ret==2 ? 0 : (ret<0 ? ret : -EIO);
}

static int hwt101_gtp_write_u8(struct i2c_client *client, u16 reg, u8 val)
{
    u8 buf[3] = { reg >> 8, reg & 0xff, val };
    struct i2c_msg msg = {
        .addr=client->addr, .flags=0, .len=3, .buf=buf,
    };
    int ret=i2c_transfer(client->adapter,&msg,1);
    return ret==1 ? 0 : (ret<0 ? ret : -EIO);
}

static int gtp_i2c_test(struct i2c_client *client)
{
    u8 id[4]={0};
    int ret=hwt101_gtp_read(client,HWT101_GTP_REG_PRODUCT_ID,id,sizeof(id));
    if (ret) return ret;
    dev_info(&client->dev,
        "HWT101 Goodix product=%c%c%c%c bus=%d addr=0x%02x\n",
        id[0]?id[0]:'?',id[1]?id[1]:'?',id[2]?id[2]:'?',id[3]?id[3]:'?',
        i2c_adapter_id(client->adapter),client->addr);
    return 0;
}

static void goodix_ts_work_func(struct work_struct *work)
{
    struct hwt101_goodix *ts=
        container_of(to_delayed_work(work),struct hwt101_goodix,work);
    u8 status=0, points[HWT101_GTP_MAX_TOUCH*8];
    int n,i,ret;

    if (ts->stopped) return;
    ret=hwt101_gtp_read(ts->client,HWT101_GTP_REG_STATUS,&status,1);
    if (ret) goto again;
    if (!(status & 0x80)) goto again;

    n=status & 0x0f;
    if (n>HWT101_GTP_MAX_TOUCH) n=HWT101_GTP_MAX_TOUCH;

    if (n) {
        ret=hwt101_gtp_read(ts->client,HWT101_GTP_REG_STATUS+1,
                           points,n*8);
        if (ret) goto clear;
        for (i=0;i<n;i++) {
            u8 *p=&points[i*8];
            int x=p[1] | (p[2]<<8);
            int y=p[3] | (p[4]<<8);
            int w=p[5] | (p[6]<<8);
            if (x<0) x=0; if (x>HWT101_GTP_X_MAX) x=HWT101_GTP_X_MAX;
            if (y<0) y=0; if (y>HWT101_GTP_Y_MAX) y=HWT101_GTP_Y_MAX;
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
        schedule_delayed_work(&ts->work,msecs_to_jiffies(HWT101_GTP_POLL_MS));
}

static int goodix_ts_probe(struct i2c_client *client,
                           const struct i2c_device_id *id)
{
    struct hwt101_goodix *ts;
    struct input_dev *input;
    int ret;

    if (!i2c_check_functionality(client->adapter,I2C_FUNC_I2C))
        return -ENODEV;
    ret=gtp_i2c_test(client);
    if (ret) {
        dev_err(&client->dev,
          "HWT101 Goodix not responding bus=%d addr=0x%02x ret=%d\n",
          i2c_adapter_id(client->adapter),client->addr,ret);
        return ret;
    }

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
        i2c_set_clientdata(client,NULL); return ret;
    }

    dev_info(&client->dev,
      "HWT101 Goodix active polling=%dms range=%dx%d\n",
      HWT101_GTP_POLL_MS,HWT101_GTP_X_MAX,HWT101_GTP_Y_MAX);
    schedule_delayed_work(&ts->work,msecs_to_jiffies(HWT101_GTP_POLL_MS));
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
    { "Goodix-TS", 0 },
    { "goodix-ts", 0 },
    { "gt9xx", 0 },
    { }
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
    printk(KERN_INFO "HWT101_GTP: install Goodix GT9280 compatibility driver\n");
    return i2c_add_driver(&goodix_ts_driver);
}
late_initcall(hwt101_goodix_init);

static void __exit hwt101_goodix_exit(void)
{
    i2c_del_driver(&goodix_ts_driver);
}
module_exit(hwt101_goodix_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("HWT101 Goodix GT9280 polling compatibility");
'''
drv.write_text(src)
m=mk.read_text()
if "hwt101_goodix.o" not in m:
    if not m.endswith("\n"): m+="\n"
    m+='obj-y += hwt101_goodix.o  # HWT101 FIX10 Goodix GT9280\n'
    mk.write_text(m)

# Gates
rs=reg.read_text()
for tok in (
 'REGULATOR_SUPPLY("lcdanalog-vcc", "k3_dev_lcd")',
 'REGULATOR_SUPPLY("lcd-vcc", "sn65dsi83")',
 'REGULATOR_SUPPLY("lcd-vcc", "1-002d")',
 '.num_consumer_supplies = 0',
 '.consumer_supplies = NULL',
):
    if tok not in rs: raise SystemExit("regulator gate failed: "+tok)
ds=drv.read_text()
for tok in ('{ "Goodix-TS", 0 }','HWT101_GTP: install','HWT101 Goodix active','0x814e','1280','800'):
    if tok not in ds: raise SystemExit("Goodix gate failed: "+tok)

print("V412_DISPLAY_TOUCH_PATCH=PASS")
print("BASE=V411B_BATTERY_FUNCTIONAL")
print("FIX10_LDO15=lcdanalog-vcc+lcd-vcc")
print("FIX10_LDO16=lcdio-vcc")
print("FIX10_LDO17=ZERO_CONSUMERS")
print("SN65_COMPAT_ALIAS=1-002d")
print("GOODIX=GT9280_COMPAT")
print("GOODIX_BUS=2")
print("GOODIX_ADDR=0x14")
print("GOODIX_MODE=POLL_20MS")
print("GOODIX_RANGE=1280x800")
print("BATTERY_HSAD_YAFFS_NAND=UNCHANGED")
