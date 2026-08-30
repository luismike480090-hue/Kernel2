/*
 * HWT101 SN65DSI83 bridge reconstruction - V2 OEM boot-sequence fix.
 *
 * Reconstructed from the working FIX10 Linux 3.0.8 kernel:
 *  - i2c driver name: sn65dsi83
 *  - I2C address observed in OEM platform data: 0x2d
 *  - enable GPIO observed in OEM dmesg: 79
 *  - regulator name recovered from strings: "lcd-vcc"
 *  - regulator voltage recovered from code: 2600000 uV
 *  - early suspend: EN=0, 10ms, regulator_disable()
 *  - late resume: regulator_enable(), 2ms, EN=1, write exact OEM register table
 *
 * This file intentionally stays on old Android early-suspend + Linux 3.0 APIs.
 */
#include <linux/module.h>
#include <linux/err.h>
#include <linux/kernel.h>
#include <linux/i2c.h>
#include <linux/gpio.h>
#include <linux/delay.h>
#include <linux/regulator/consumer.h>
#include <linux/earlysuspend.h>
#include "sn65dsi83_oem_table.h"

struct hwt101_sn65_pdata {
    int en_gpio;
};

static struct i2c_client *g_client;
static struct regulator *g_lcd_vcc;
static int g_en_gpio = 79;
static struct early_suspend g_early;

static int hwt101_sn65_write_regs(struct i2c_client *client)
{
    int i, ret = 0;
    u8 tx[2];
    struct i2c_msg msg;

    if (!client || !client->adapter)
        return -ENODEV;

    for (i = 0; i < HWT101_SN65_REG_COUNT; i++) {
        tx[0] = hwt101_sn65_regs[i].reg;
        tx[1] = hwt101_sn65_regs[i].val;
        msg.addr = client->addr;
        msg.flags = 0;
        msg.len = 2;
        msg.buf = tx;
        ret = i2c_transfer(client->adapter, &msg, 1);
        if (ret < 0) {
            printk(KERN_ERR "sn65dsi83: i2c write reg 0x%02x failed: %d\n",
                   tx[0], ret);
        }
        udelay(500);
    }
    return ret < 0 ? ret : 0;
}

static void hwt101_sn65_early_suspend(struct early_suspend *h)
{
    printk(KERN_INFO "sn65dsi83_early_supend+\n");
    gpio_set_value(g_en_gpio, 0);
    msleep(10);
    if (g_lcd_vcc && !IS_ERR(g_lcd_vcc))
        regulator_disable(g_lcd_vcc);
    printk(KERN_INFO "sn65dsi83_early_supend-\n");
}

static void hwt101_sn65_late_resume(struct early_suspend *h)
{
    int ret;
    printk(KERN_INFO "sn65dsi83_late_resume enter +\n");
    if (g_lcd_vcc && !IS_ERR(g_lcd_vcc)) {
        ret = regulator_enable(g_lcd_vcc);
        if (ret)
            printk(KERN_ERR "sn65dsi83: failed regulator enable: %d\n", ret);
    }
    msleep(2);
    gpio_set_value(g_en_gpio, 1);
    hwt101_sn65_write_regs(g_client);
    printk(KERN_INFO "sn65dsi83_late_resume leave -\n");
}

static int hwt101_sn65_probe(struct i2c_client *client,
                             const struct i2c_device_id *id)
{
    struct hwt101_sn65_pdata *pdata = client->dev.platform_data;
    int ret;

    g_client = client;
    if (pdata && gpio_is_valid(pdata->en_gpio))
        g_en_gpio = pdata->en_gpio;

    printk(KERN_INFO "==sn65dsi83_probe in , pdata->en_gpio = %d =\n", g_en_gpio);

    g_lcd_vcc = regulator_get(&client->dev, "lcd-vcc");
    if (IS_ERR(g_lcd_vcc)) {
        printk(KERN_ERR "sn65dsi83: Regulator Get Failed.\n");
        return -ENODEV;
    }

    ret = regulator_set_voltage(g_lcd_vcc, 2600000, 2600000);
    if (ret) {
        printk(KERN_ERR "sn65dsi83: failed to set voltage of regulator!\n");
        return ret;
    }

    msleep(10);
    ret = regulator_enable(g_lcd_vcc);
    if (ret)
        return ret;
    msleep(10);

    ret = gpio_request(g_en_gpio, "sn65dsi83_en");
    if (ret)
        return ret;
    gpio_direction_output(g_en_gpio, 1);
    msleep(10);

    /*
     * IMPORTANT: FIX10 OEM does NOT program the SN65 register table in probe.
     * It only verifies I2C_FUNC_I2C here. The exact 43-register table is
     * written later from late_resume(), after lcd-vcc is re-enabled and
     * EN GPIO is raised. Reprogramming the bridge during probe can destroy
     * the bootloader/fastboot display state and was the leading V1 gray-screen
     * mismatch.
     */
    if (!i2c_check_functionality(client->adapter, I2C_FUNC_I2C)) {
        printk(KERN_ERR "sn65dsi83: adapter lacks I2C_FUNC_I2C\n");
        return -ENODEV;
    }

    g_early.level = 149; /* exact level recovered from FIX10 machine code */
    g_early.suspend = hwt101_sn65_early_suspend;
    g_early.resume = hwt101_sn65_late_resume;
    register_early_suspend(&g_early);

    printk(KERN_INFO "==probe over , pdata->en_gpio = %d =\n", g_en_gpio);
    return 0;
}

static int hwt101_sn65_remove(struct i2c_client *client)
{
    unregister_early_suspend(&g_early);
    gpio_set_value(g_en_gpio, 0);
    gpio_free(g_en_gpio);
    if (g_lcd_vcc && !IS_ERR(g_lcd_vcc)) {
        regulator_disable(g_lcd_vcc);
        regulator_put(g_lcd_vcc);
    }
    g_client = NULL;
    return 0;
}

static const struct i2c_device_id hwt101_sn65_id[] = {
    { "sn65dsi83", 0 },
    { }
};
MODULE_DEVICE_TABLE(i2c, hwt101_sn65_id);

static struct i2c_driver hwt101_sn65_driver = {
    .driver = {
        .name = "sn65dsi83",
    },
    .probe = hwt101_sn65_probe,
    .remove = hwt101_sn65_remove,
    .id_table = hwt101_sn65_id,
};

static int __init hwt101_sn65_init(void)
{
    printk(KERN_INFO "==sn65dsi83_init==\n");
    return i2c_add_driver(&hwt101_sn65_driver);
}
module_init(hwt101_sn65_init);

static void __exit hwt101_sn65_exit(void)
{
    i2c_del_driver(&hwt101_sn65_driver);
}
module_exit(hwt101_sn65_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("HWT101 reconstructed SN65DSI83 bridge driver");
