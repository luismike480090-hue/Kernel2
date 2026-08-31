/*
 * HWT101 SN65DSI83 bridge driver reconstructed from the WORKING FIX10 kernel.
 * V3.36 corrects two decisive differences found by direct ARM disassembly:
 *
 *  1. OEM probe powers lcd-vcc and asserts the enable GPIO, but DOES NOT call
 *     ti_write_regs().  The bootloader-programmed bridge state is preserved
 *     during initial Linux boot.
 *  2. OEM ti_write_regs() copies exactly 86 bytes from OEM table + 4 and sends
 *     43 two-byte I2C messages.  See sn65dsi83_oem_table.h.
 *
 * OEM sequence recovered at these addresses:
 *   probe          0xc0270f90
 *   ti_reset       0xc0271118
 *   ti_write_regs  0xc02711d0
 *   early_suspend  0xc02712f8
 *   late_resume    0xc027137c
 */
#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/i2c.h>
#include <linux/gpio.h>
#include <linux/delay.h>
#include <linux/err.h>
#include <linux/regulator/consumer.h>
#include <linux/earlysuspend.h>
#include "sn65dsi83_oem_table.h"

struct hwt101_sn65_pdata { int en_gpio; };
static struct i2c_client *g_client;
static struct regulator *g_lcd_vcc;
static int g_en_gpio = 79;
static struct early_suspend g_early;

/* OEM ti_write_regs: 43 independent I2C transfers, 500 us between transfers. */
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
        if (ret < 0)
            printk(KERN_ERR "sn65dsi83: i2c write reg 0x%02x failed: %d\n", tx[0], ret);
        udelay(500);
    }
    return ret < 0 ? ret : 0;
}

/* Exported OEM-style helper.  The OEM implementation sends two 2-byte I2C
 * messages separated by 1 ms.  It is retained for ABI/diagnostic parity but
 * is deliberately NOT invoked by probe. */
int hwt101_sn65_ti_reset(void)
{
    u8 a[2] = { 0x09, 0x01 };
    u8 b[2] = { 0x09, 0x00 };
    struct i2c_msg m;
    int ret;
    if (!g_client || !g_client->adapter)
        return -ENODEV;
    m.addr = g_client->addr; m.flags = 0; m.len = 2; m.buf = a;
    ret = i2c_transfer(g_client->adapter, &m, 1);
    msleep(1);
    m.buf = b;
    if (i2c_transfer(g_client->adapter, &m, 1) < 0 && ret >= 0)
        ret = -EIO;
    return ret < 0 ? ret : 0;
}
EXPORT_SYMBOL(hwt101_sn65_ti_reset);

static void hwt101_sn65_early_suspend(struct early_suspend *h)
{
    int ret;
    printk(KERN_INFO "sn65dsi83_early_supend+\n");
    gpio_set_value(g_en_gpio, 0);
    msleep(10);
    ret = (g_lcd_vcc && !IS_ERR(g_lcd_vcc)) ? regulator_disable(g_lcd_vcc) : -ENODEV;
    if (ret)
        printk(KERN_ERR "sn65dsi83: regulator disable failed: %d\n", ret);
    printk(KERN_INFO "sn65dsi83_early_supend-\n");
}

static void hwt101_sn65_late_resume(struct early_suspend *h)
{
    int ret;
    printk(KERN_INFO "sn65dsi83_late_resume enter +\n");
    ret = (g_lcd_vcc && !IS_ERR(g_lcd_vcc)) ? regulator_enable(g_lcd_vcc) : -ENODEV;
    if (ret) {
        printk(KERN_ERR "sn65dsi83: regulator enable failed: %d\n", ret);
        return;
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
        return -ENODEV;
    }
    msleep(10);

    ret = regulator_enable(g_lcd_vcc);
    if (ret) {
        printk(KERN_ERR "sn65dsi83: failed to enable regulator!\n");
        return -ENODEV;
    }
    msleep(10);

    ret = gpio_request(g_en_gpio, "sn65dsi83_en");
    if (ret)
        return -ENODEV;
    gpio_direction_output(g_en_gpio, 1);
    msleep(10);

    /* EXACT OEM BOOT BEHAVIOUR:
     * Do NOT program the SN65 register table here.  The working OEM kernel
     * checks I2C adapter functionality and then registers early-suspend.
     * The bootloader's bridge programming therefore survives initial boot. */
    if (!i2c_check_functionality(client->adapter, I2C_FUNC_I2C))
        return -ENODEV;

    g_early.level = 149;
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
    { "sn65dsi83", 0 }, { }
};
MODULE_DEVICE_TABLE(i2c, hwt101_sn65_id);

static struct i2c_driver hwt101_sn65_driver = {
    .driver = { .name = "sn65dsi83", },
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
MODULE_DESCRIPTION("HWT101 OEM-behaviour SN65DSI83 bridge driver V3.36");
