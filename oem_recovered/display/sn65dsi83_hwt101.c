/* HWT101 SN65DSI83 V3.36 -- reconstructed from working FIX10 ARM code. */
#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/i2c.h>
#include <linux/gpio.h>
#include <linux/delay.h>
#include <linux/err.h>
#include <linux/regulator/consumer.h>
#include <linux/earlysuspend.h>
#include "sn65dsi83_oem_table.h"

struct sn65dsi83_platform_data { int en_gpio; };
static struct i2c_client *sn65_client;
static struct regulator *sn65_lcd_vcc;
static int sn65_en_gpio = 79;
static struct early_suspend sn65_early;

/* OEM 0xc02711d0: 43 independent 2-byte transfers, 500 us apart. */
int ti_write_regs(void)
{
    int i, ret = 0;
    u8 tx[2];
    struct i2c_msg msg;
    if (!sn65_client || !sn65_client->adapter) return -ENODEV;
    for (i = 0; i < HWT101_SN65_REG_COUNT; i++) {
        tx[0]=hwt101_sn65_regs[i].reg; tx[1]=hwt101_sn65_regs[i].val;
        msg.addr=sn65_client->addr; msg.flags=0; msg.len=2; msg.buf=tx;
        ret=i2c_transfer(sn65_client->adapter,&msg,1);
        if (ret < 0) printk(KERN_ERR "sn65dsi83: i2c transfer failed %d\n",ret);
        udelay(500);
    }
    return ret < 0 ? ret : 0;
}
EXPORT_SYMBOL(ti_write_regs);

/* OEM 0xc0271118: reset transaction pair separated by 1 ms. */
int ti_reset(void)
{
    u8 a[2]={0x09,0x01}, b[2]={0x09,0x00};
    struct i2c_msg m; int ret;
    if (!sn65_client || !sn65_client->adapter) return -ENODEV;
    m.addr=sn65_client->addr; m.flags=0; m.len=2; m.buf=a;
    ret=i2c_transfer(sn65_client->adapter,&m,1);
    msleep(1); m.buf=b;
    if (i2c_transfer(sn65_client->adapter,&m,1)<0 && ret>=0) ret=-EIO;
    return ret < 0 ? ret : 0;
}
EXPORT_SYMBOL(ti_reset);

static void sn65dsi83_early_suspend(struct early_suspend *h)
{
    int ret;
    printk(KERN_INFO "sn65dsi83_early_supend+\n");
    gpio_set_value(sn65_en_gpio,0);
    msleep(10);
    ret=(sn65_lcd_vcc && !IS_ERR(sn65_lcd_vcc)) ? regulator_disable(sn65_lcd_vcc) : -ENODEV;
    if (ret) printk(KERN_ERR "sn65dsi83 regulator disable failed %d\n",ret);
    printk(KERN_INFO "sn65dsi83_early_supend-\n");
}

static void sn65dsi83_late_resume(struct early_suspend *h)
{
    int ret;
    printk(KERN_INFO "sn65dsi83_late_resume enter +\n");
    ret=(sn65_lcd_vcc && !IS_ERR(sn65_lcd_vcc)) ? regulator_enable(sn65_lcd_vcc) : -ENODEV;
    if (ret) { printk(KERN_ERR "sn65dsi83 regulator enable failed %d\n",ret); return; }
    msleep(2);
    gpio_set_value(sn65_en_gpio,1);
    ti_write_regs();
    printk(KERN_INFO "sn65dsi83_late_resume leave -\n");
}

/* OEM probe 0xc0270f90. Critical finding: probe NEVER calls ti_write_regs().
 * It only acquires/sets/enables lcd-vcc, asserts EN, waits, checks adapter
 * functionality, then registers early suspend. Thus bootloader bridge state
 * is preserved through initial Linux boot. */
static int sn65dsi83_probe(struct i2c_client *client,const struct i2c_device_id *id)
{
    struct sn65dsi83_platform_data *pdata=client->dev.platform_data;
    int ret;
    sn65_client=client;
    if (pdata && gpio_is_valid(pdata->en_gpio)) sn65_en_gpio=pdata->en_gpio;
    printk(KERN_INFO "==sn65dsi83_probe in , pdata->en_gpio = %d =\n",sn65_en_gpio);
    sn65_lcd_vcc=regulator_get(&client->dev,"lcd-vcc");
    if (IS_ERR(sn65_lcd_vcc)) { printk(KERN_ERR "Regulator Get Failed.\n"); return -ENODEV; }
    ret=regulator_set_voltage(sn65_lcd_vcc,2600000,2600000);
    if (ret) { printk(KERN_ERR "failed to set voltage of regulator!\n"); return -ENODEV; }
    msleep(10);
    ret=regulator_enable(sn65_lcd_vcc);
    if (ret) { printk(KERN_ERR "failed to enable regulator!\n"); return -ENODEV; }
    msleep(10);
    ret=gpio_request(sn65_en_gpio,"sn65dsi83_en");
    if (ret) return -ENODEV;
    gpio_direction_output(sn65_en_gpio,1);
    msleep(10);
    if (!i2c_check_functionality(client->adapter,I2C_FUNC_I2C)) return -ENODEV;
    sn65_early.level=149;
    sn65_early.suspend=sn65dsi83_early_suspend;
    sn65_early.resume=sn65dsi83_late_resume;
    register_early_suspend(&sn65_early);
    printk(KERN_INFO "==probe over , pdata->en_gpio = %d =\n",sn65_en_gpio);
    return 0;
}

static int sn65dsi83_remove(struct i2c_client *client)
{
    unregister_early_suspend(&sn65_early);
    gpio_set_value(sn65_en_gpio,0); gpio_free(sn65_en_gpio);
    if (sn65_lcd_vcc && !IS_ERR(sn65_lcd_vcc)) { regulator_disable(sn65_lcd_vcc); regulator_put(sn65_lcd_vcc); }
    sn65_client=NULL; return 0;
}

static const struct i2c_device_id sn65dsi83_id[]={{"sn65dsi83",0},{}};
MODULE_DEVICE_TABLE(i2c,sn65dsi83_id);
static struct i2c_driver sn65dsi83_driver={
    .driver={.name="sn65dsi83"}, .probe=sn65dsi83_probe,
    .remove=sn65dsi83_remove, .id_table=sn65dsi83_id,
};
static int __init sn65dsi83_init(void)
{
    printk(KERN_INFO "==sn65dsi83_init==\n");
    return i2c_add_driver(&sn65dsi83_driver);
}
module_init(sn65dsi83_init);
static void __exit sn65dsi83_exit(void){i2c_del_driver(&sn65dsi83_driver);}
module_exit(sn65dsi83_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("HWT101 OEM-behaviour SN65DSI83 V3.36");
