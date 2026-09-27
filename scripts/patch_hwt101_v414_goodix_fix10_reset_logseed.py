#!/usr/bin/env python3
from pathlib import Path
import re, sys

root=Path(sys.argv[1] if len(sys.argv)>1 else "kernel")

# V4.14 is deliberately based on V4.13:
# - keep framebuffer stride=5120, battery, HSAD, YAFFS64, NAND guard
# - restore the exact FIX10 Goodix power/reset GPIO sequence
# - seed log_main from the kernel to prove the logger read path independently
#   of Android userspace logging.

g=root/"drivers/input/touchscreen/hwt101_goodix.c"
if not g.exists():
    raise SystemExit("V413 Goodix source missing")

src=r'''/*
 * HWT101 Goodix GT9280 compatibility driver V4.14.
 *
 * Hardware values reverse-verified from the original FIX10 kernel:
 *   I2C bus 2, address 0x14
 *   INT    GPIO 157
 *   RESET  GPIO 156
 *   ENABLE GPIO 61
 *
 * FIX10 reset/address-selection sequence:
 *   ENABLE=1, wait 2 ms
 *   RESET=0, wait 20 ms
 *   INT=1 for address 0x14, wait 2 ms
 *   RESET=1, wait 6 ms
 *   RESET=input
 *   INT=0, wait 50 ms, INT=input
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
#include <linux/mux.h>

#define HWT101_GTP_REG_PRODUCT_ID 0x8140
#define HWT101_GTP_REG_STATUS     0x814e
#define HWT101_GTP_MAX_TOUCH      5
#define HWT101_GTP_X_MAX          1280
#define HWT101_GTP_Y_MAX          800
#define HWT101_GTP_POLL_MS        20
#define HWT101_GTP_RETRY_MS       1000

#define HWT101_GTP_GPIO_INT       157
#define HWT101_GTP_GPIO_RESET     156
#define HWT101_GTP_GPIO_ENABLE    61

struct hwt101_goodix {
    struct i2c_client *client;
    struct input_dev *input;
    struct delayed_work work;
    int stopped;
    int online;
    int fail_count;
    int reset_count;
    int gpio_en_requested;
    int gpio_int_requested;
    int gpio_reset_requested;
};

static int hwt101_gtp_read(struct i2c_client *client, u16 reg, u8 *data, int len)
{
    u8 addr[2] = { reg >> 8, reg & 0xff };
    struct i2c_msg msg[2];
    int ret;

    msg[0].addr=client->addr;
    msg[0].flags=0;
    msg[0].len=2;
    msg[0].buf=addr;
    msg[1].addr=client->addr;
    msg[1].flags=I2C_M_RD;
    msg[1].len=len;
    msg[1].buf=data;

    ret=i2c_transfer(client->adapter,msg,2);
    return ret==2 ? 0 : (ret<0 ? ret : -EIO);
}

static int hwt101_gtp_write_u8(struct i2c_client *client, u16 reg, u8 val)
{
    u8 buf[3] = { reg >> 8, reg & 0xff, val };
    struct i2c_msg msg = {
        .addr=client->addr, .flags=0, .len=3, .buf=buf
    };
    int ret=i2c_transfer(client->adapter,&msg,1);

    return ret==1 ? 0 : (ret<0 ? ret : -EIO);
}

static void hwt101_gtp_try_iomux(struct i2c_client *client)
{
    struct iomux_block *block;
    struct block_config *config;
    int ret;

    block=iomux_get_block("block_ts");
    config=iomux_get_blockconfig("block_ts");
    if (!block || !config) {
        dev_warn(&client->dev,
            "HWT101_GTP FIX10 block_ts unavailable; continuing like OEM\n");
        return;
    }

    ret=blockmux_set(block,config,NORMAL);
    if (ret)
        dev_warn(&client->dev,
            "HWT101_GTP FIX10 block_ts NORMAL failed ret=%d; continuing\n",
            ret);
    else
        dev_info(&client->dev,
            "HWT101_GTP FIX10 block_ts NORMAL\n");
}

static int hwt101_gtp_reset_guitar(struct hwt101_goodix *ts, int ms)
{
    struct i2c_client *client=ts->client;
    int ret;

    ret=gpio_direction_output(HWT101_GTP_GPIO_RESET,0);
    if (ret) {
        dev_err(&client->dev,
            "HWT101_GTP reset gpio %d LOW failed ret=%d\n",
            HWT101_GTP_GPIO_RESET,ret);
        return ret;
    }
    msleep(ms);

    /* Goodix GT9xx hardware-address selection: HIGH selects 0x14. */
    ret=gpio_direction_output(HWT101_GTP_GPIO_INT,
                             client->addr==0x14 ? 1 : 0);
    if (ret) {
        dev_err(&client->dev,
            "HWT101_GTP int gpio %d address-select failed ret=%d\n",
            HWT101_GTP_GPIO_INT,ret);
        return ret;
    }
    msleep(2);

    ret=gpio_direction_output(HWT101_GTP_GPIO_RESET,1);
    if (ret) {
        dev_err(&client->dev,
            "HWT101_GTP reset gpio %d HIGH failed ret=%d\n",
            HWT101_GTP_GPIO_RESET,ret);
        return ret;
    }
    msleep(6);

    ret=gpio_direction_input(HWT101_GTP_GPIO_RESET);
    if (ret)
        dev_warn(&client->dev,
            "HWT101_GTP reset gpio input failed ret=%d\n",ret);

    /* FIX10 gtp_int_sync(50). */
    ret=gpio_direction_output(HWT101_GTP_GPIO_INT,0);
    if (ret) {
        dev_err(&client->dev,
            "HWT101_GTP int sync LOW failed ret=%d\n",ret);
        return ret;
    }
    msleep(50);

    ret=gpio_direction_input(HWT101_GTP_GPIO_INT);
    if (ret) {
        dev_err(&client->dev,
            "HWT101_GTP int gpio input failed ret=%d\n",ret);
        return ret;
    }

    ts->reset_count++;
    dev_info(&client->dev,
        "HWT101_GTP FIX10 reset complete en=%d rst=%d int=%d addr=0x%02x count=%d\n",
        HWT101_GTP_GPIO_ENABLE,HWT101_GTP_GPIO_RESET,HWT101_GTP_GPIO_INT,
        client->addr,ts->reset_count);
    return 0;
}

static void hwt101_gtp_free_gpios(struct hwt101_goodix *ts)
{
    if (ts->gpio_reset_requested) {
        gpio_free(HWT101_GTP_GPIO_RESET);
        ts->gpio_reset_requested=0;
    }
    if (ts->gpio_int_requested) {
        gpio_free(HWT101_GTP_GPIO_INT);
        ts->gpio_int_requested=0;
    }
    if (ts->gpio_en_requested) {
        gpio_free(HWT101_GTP_GPIO_ENABLE);
        ts->gpio_en_requested=0;
    }
}

static int hwt101_gtp_hw_prepare(struct hwt101_goodix *ts)
{
    struct i2c_client *client=ts->client;
    int ret;

    hwt101_gtp_try_iomux(client);

    ret=gpio_request(HWT101_GTP_GPIO_ENABLE,"hwt101_gtp_enable");
    if (ret) {
        dev_err(&client->dev,
            "HWT101_GTP gpio_request ENABLE=%d failed ret=%d\n",
            HWT101_GTP_GPIO_ENABLE,ret);
        return ret;
    }
    ts->gpio_en_requested=1;

    ret=gpio_direction_output(HWT101_GTP_GPIO_ENABLE,1);
    if (ret) {
        dev_err(&client->dev,
            "HWT101_GTP ENABLE=%d HIGH failed ret=%d\n",
            HWT101_GTP_GPIO_ENABLE,ret);
        goto fail;
    }
    msleep(2);

    ret=gpio_request(HWT101_GTP_GPIO_INT,"hwt101_gtp_int");
    if (ret) {
        dev_err(&client->dev,
            "HWT101_GTP gpio_request INT=%d failed ret=%d\n",
            HWT101_GTP_GPIO_INT,ret);
        goto fail;
    }
    ts->gpio_int_requested=1;

    ret=gpio_request(HWT101_GTP_GPIO_RESET,"hwt101_gtp_reset");
    if (ret) {
        dev_err(&client->dev,
            "HWT101_GTP gpio_request RESET=%d failed ret=%d\n",
            HWT101_GTP_GPIO_RESET,ret);
        goto fail;
    }
    ts->gpio_reset_requested=1;

    dev_info(&client->dev,
        "HWT101_GTP FIX10 GPIO prepare PASS enable=%d int=%d reset=%d\n",
        HWT101_GTP_GPIO_ENABLE,HWT101_GTP_GPIO_INT,HWT101_GTP_GPIO_RESET);

    ret=hwt101_gtp_reset_guitar(ts,20);
    if (ret)
        goto fail;

    return 0;

fail:
    hwt101_gtp_free_gpios(ts);
    return ret;
}

static int hwt101_gtp_test(struct hwt101_goodix *ts)
{
    u8 id[4]={0};
    int ret=hwt101_gtp_read(ts->client,HWT101_GTP_REG_PRODUCT_ID,
                            id,sizeof(id));
    if (ret)
        return ret;
    if (!id[0] && !id[1] && !id[2] && !id[3])
        return -ENODEV;

    if (!ts->online)
        dev_info(&ts->client->dev,
          "HWT101_GTP ONLINE product=%c%c%c%c bus=%d addr=0x%02x resets=%d\n",
          id[0]?id[0]:'?',id[1]?id[1]:'?',id[2]?id[2]:'?',id[3]?id[3]:'?',
          i2c_adapter_id(ts->client->adapter),ts->client->addr,
          ts->reset_count);

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

    if (ts->stopped)
        return;

    if (!ts->online) {
        /* Unlike V4.13, retry the OEM hardware reset, not just I2C reads. */
        ret=hwt101_gtp_reset_guitar(ts,20);
        if (!ret)
            ret=hwt101_gtp_test(ts);

        if (ret) {
            ts->fail_count++;
            if ((ts->fail_count % 10)==1)
                dev_warn(&ts->client->dev,
                  "HWT101_GTP offline after FIX10 reset ret=%d try=%d resets=%d\n",
                  ret,ts->fail_count,ts->reset_count);
            delay=HWT101_GTP_RETRY_MS;
            goto again;
        }
    }

    ret=hwt101_gtp_read(ts->client,HWT101_GTP_REG_STATUS,&status,1);
    if (ret) {
        if (++ts->fail_count >= 10) {
            ts->online=0;
            dev_warn(&ts->client->dev,
              "HWT101_GTP lost controller ret=%d; FIX10 reset on next retry\n",
              ret);
        }
        delay=HWT101_GTP_RETRY_MS;
        goto again;
    }
    ts->fail_count=0;

    if (!(status & 0x80))
        goto again;

    n=status & 0x0f;
    if (n>HWT101_GTP_MAX_TOUCH)
        n=HWT101_GTP_MAX_TOUCH;

    if (n) {
        ret=hwt101_gtp_read(ts->client,HWT101_GTP_REG_STATUS+1,
                            points,n*8);
        if (ret)
            goto clear;

        for (i=0;i<n;i++) {
            u8 *p=&points[i*8];
            int x=p[1] | (p[2]<<8);
            int y=p[3] | (p[4]<<8);
            int w=p[5] | (p[6]<<8);

            if (x>HWT101_GTP_X_MAX) x=HWT101_GTP_X_MAX;
            if (y>HWT101_GTP_Y_MAX) y=HWT101_GTP_Y_MAX;
            if (w<1) w=1;
            if (w>255) w=255;

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

    dev_info(&client->dev,
      "HWT101_GTP V4.14 FIX10 HW init bus=%d addr=0x%02x\n",
      i2c_adapter_id(client->adapter),client->addr);

    if (!i2c_check_functionality(client->adapter,I2C_FUNC_I2C))
        return -ENODEV;

    ts=kzalloc(sizeof(*ts),GFP_KERNEL);
    if (!ts)
        return -ENOMEM;

    ts->client=client;
    INIT_DELAYED_WORK(&ts->work,goodix_ts_work_func);
    i2c_set_clientdata(client,ts);

    ret=hwt101_gtp_hw_prepare(ts);
    if (ret) {
        i2c_set_clientdata(client,NULL);
        kfree(ts);
        return ret;
    }

    ret=hwt101_gtp_test(ts);
    if (ret)
        dev_warn(&client->dev,
          "HWT101_GTP initial FIX10 reset done but I2C ret=%d; background retry enabled\n",
          ret);

    input=input_allocate_device();
    if (!input) {
        hwt101_gtp_free_gpios(ts);
        i2c_set_clientdata(client,NULL);
        kfree(ts);
        return -ENOMEM;
    }

    ts->input=input;
    input->name="goodix-ts";
    input->id.bustype=BUS_I2C;
    input->dev.parent=&client->dev;
    set_bit(EV_ABS,input->evbit);
    input_set_abs_params(input,ABS_MT_POSITION_X,0,HWT101_GTP_X_MAX,0,0);
    input_set_abs_params(input,ABS_MT_POSITION_Y,0,HWT101_GTP_Y_MAX,0,0);
    input_set_abs_params(input,ABS_MT_TOUCH_MAJOR,0,255,0,0);

    ret=input_register_device(input);
    if (ret) {
        input_free_device(input);
        hwt101_gtp_free_gpios(ts);
        i2c_set_clientdata(client,NULL);
        kfree(ts);
        return ret;
    }

    dev_info(&client->dev,
      "HWT101_GTP input registered; FIX10 reset sequence active\n");

    schedule_delayed_work(&ts->work,
        msecs_to_jiffies(ts->online ? HWT101_GTP_POLL_MS :
                                      HWT101_GTP_RETRY_MS));
    return 0;
}

static int goodix_ts_remove(struct i2c_client *client)
{
    struct hwt101_goodix *ts=i2c_get_clientdata(client);

    if (!ts)
        return 0;

    ts->stopped=1;
    cancel_delayed_work_sync(&ts->work);
    input_unregister_device(ts->input);
    hwt101_gtp_free_gpios(ts);
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
    .driver={
        .name="Goodix-TS",
        .owner=THIS_MODULE
    },
    .probe=goodix_ts_probe,
    .remove=goodix_ts_remove,
    .id_table=goodix_ts_id,
};

static int __init hwt101_goodix_init(void)
{
    printk(KERN_INFO
      "HWT101_GTP: V4.14 FIX10 reset driver en=61 reset=156 int=157 addr=0x14\n");
    return i2c_add_driver(&goodix_ts_driver);
}
late_initcall(hwt101_goodix_init);

static void __exit hwt101_goodix_exit(void)
{
    i2c_del_driver(&goodix_ts_driver);
}
module_exit(hwt101_goodix_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("HWT101 Goodix GT9280 FIX10 GPIO/reset compatibility V4.14");
'''
g.write_text(src)

# Logger diagnostic: V4.13 proved that removing the kernel NV gate alone did
# not populate logcat. Seed log_main directly in the kernel so adb logcat can
# prove/disprove the kernel reader path independently of Android liblog.
logf=root/"drivers/staging/android/logger.c"
s=logf.read_text()

anchor='''static struct logger_log *get_log_from_minor(int minor)
{
'''
if anchor not in s:
    raise SystemExit("logger helper insertion anchor missing")

helper=r'''
#ifndef CONFIG_K3_LOG
static void hwt101_logger_seed_main(void)
{
    struct logger_entry header;
    struct timespec now;
    static const unsigned char payload[] = {
        ANDROID_LOG_INFO,
        'H','W','T','1','0','1','_','K','E','R','N','E','L',0,
        'L','O','G','G','E','R','_','R','I','N','G','_','O','K','_',
        'V','4','1','4',0
    };
    struct logger_log *log=&log_main;

    memset(&header,0,sizeof(header));
    now=current_kernel_time();
    header.pid=0;
    header.tid=0;
    header.sec=now.tv_sec;
    header.nsec=now.tv_nsec;
    header.len=sizeof(payload);

    mutex_lock(&log->mutex);
    fix_up_readers(log,sizeof(header)+sizeof(payload));
    do_write_log(log,&header,sizeof(header));
    do_write_log(log,payload,sizeof(payload));
    mutex_unlock(&log->mutex);

    wake_up_interruptible(&log->wq);
    printk(KERN_INFO
      "HWT101_LOGGER_SEED: log_main seeded LOGGER_RING_OK_V414 len=%u\n",
      (unsigned int)sizeof(payload));
}
#endif

'''
s=s.replace(anchor,helper+anchor,1)

call_anchor='''    //huangwen 2012-09-05 end
    return ret;
}
device_initcall(logger_init);
'''
call_new='''    //huangwen 2012-09-05 end
#ifndef CONFIG_K3_LOG
    hwt101_logger_seed_main();
#endif
    return ret;
}
device_initcall(logger_init);
'''
if call_anchor not in s:
    raise SystemExit("logger seed call anchor missing")
s=s.replace(call_anchor,call_new,1)
logf.write_text(s)

# Gates.
gs=g.read_text()
for tok in (
    "HWT101_GTP_GPIO_INT       157",
    "HWT101_GTP_GPIO_RESET     156",
    "HWT101_GTP_GPIO_ENABLE    61",
    "gpio_direction_output(HWT101_GTP_GPIO_RESET,0)",
    "client->addr==0x14 ? 1 : 0",
    "gpio_direction_output(HWT101_GTP_GPIO_RESET,1)",
    "gpio_direction_output(HWT101_GTP_GPIO_INT,0)",
    "HWT101_GTP FIX10 reset complete",
    "V4.14 FIX10 reset driver"
):
    assert tok in gs

ls=logf.read_text()
assert "HWT101_LOGGER_SEED" in ls
assert "LOGGER_RING_OK_V414" in ls
assert "hwt101_logger_seed_main();" in ls
assert "HWT101: FIX10 userspace expects all Android log buffers writable." in ls

# Preserve V4.13 display/NAND fixes.
fbh=(root/"drivers/video/k3/k3_fb.h").read_text()
assert "CONFIG_FB_STRIDE_64BYTES_ODD_ALIGN" not in fbh
ns=(root/"drivers/mtd/nand/hinand_hwt101.c").read_text()
assert "ALLOW PAGEPROG" not in ns and "ALLOW ERASE2" not in ns
assert "BLOCK PAGEPROG" in ns and "BLOCK ERASE2" in ns

print("V414_PATCH=PASS")
print("BASE=V4.13")
print("GOODIX_FIX10_GPIO_ENABLE=61")
print("GOODIX_FIX10_GPIO_RESET=156")
print("GOODIX_FIX10_GPIO_INT=157")
print("GOODIX_FIX10_ADDR=0x14")
print("GOODIX_FIX10_RESET_MS=20")
print("GOODIX_RETRY=HW_RESET_1000MS")
print("LOGGER_KERNEL_SEED=LOGGER_RING_OK_V414")
print("FRAMEBUFFER_STRIDE_FIX=PRESERVED")
print("BATTERY_HSAD_YAFFS_NAND=PRESERVED")
