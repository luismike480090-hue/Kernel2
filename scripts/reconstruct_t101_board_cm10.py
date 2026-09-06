#!/usr/bin/env python3
from pathlib import Path
import re, sys

if len(sys.argv) != 2:
    raise SystemExit('usage: reconstruct_t101_board_cm10.py <kernel-tree>')

K = Path(sys.argv[1])
p = K / 'arch/arm/mach-k3v2/board-k3v2oem1.c'
s = p.read_text(errors='ignore')

# T101 FIX10 recovered board facts (corrected KALLSYMS/ARM disassembly):
# platform devices=21; I2C bus counts=1/10/2; Toshiba MDW70; SN65DSI83 @0x2d.
if '#include <linux/wakelock.h>' not in s:
    s = s.replace('#include <linux/i2c.h>', '#include <linux/i2c.h>\n#include <linux/wakelock.h>\n#include <linux/power/bq2419x_charger.h>', 1)

# cm-10.1 carries two stale, unconditional Synaptics board-info arrays whose
# pdata declarations disappear with its own defconfig. They are not the T101
# topology anyway, so make them inert before installing the recovered arrays.
pat = re.compile(r'static struct i2c_board_info hisik3_i2c1_tp_devs\[\]\s*=\s*\{.*?\n\};\s*\n\s*static struct i2c_board_info hisik3_i2c2_tp_devs\[\]\s*=\s*\{.*?\n\};', re.S)
rep = '''static struct i2c_board_info hisik3_i2c1_tp_devs[] = {
    { .type = "hwt101-unused-i2c1-tp", .addr = 0x70 },
};
static struct i2c_board_info hisik3_i2c2_tp_devs[] = {
    { .type = "hwt101-unused-i2c2-tp", .addr = 0x70 },
};'''
s, n = pat.subn(rep, s, count=1)
if n != 1:
    raise SystemExit('ERROR: stale cm10 touch arrays not found')

marker = '/* please add platform device in the struct.*/'
pos = s.find(marker)
if pos < 0:
    raise SystemExit('ERROR: public device marker not found')

inject = r'''
/* -------------------------------------------------------------------------
 * HWT101 / T101 FIX10 OEM BOARD RECOVERY
 * Reconstructed from the working 2014 FIX10 binary, not from S10 guesses.
 * Do not add SWAP/ZRAM changes here; V3.49 is boot-parity only.
 * ------------------------------------------------------------------------- */
struct hwt101_sn65_platform_data { int en_gpio; };
static struct hwt101_sn65_platform_data hwt101_sn65_pdata = { .en_gpio = 79 };

/* Raw OEM pdata @ c07e0188 decoded with the donor's exact struct layout:
 * 1800mA, 4208mV, termination=0, input-limit=1800mA, GPIO_9_2 (=74).
 */
static struct bq2419x_platform_data hwt101_bq2419x_pdata = {
    .max_charger_currentmA = 1800,
    .max_charger_voltagemV = 4208,
    .termination_currentmA = 0,
    .max_cin_limit_currentmA = 1800,
    .gpio = GPIO_9_2,
};

/* Keep exact platform names visible even while the corresponding optional
 * userspace-facing drivers remain disabled in this boot-parity experiment. */
static struct platform_device hwt101_bq_bci_device = {
    .name = "bq_bci_battery", .id = 1,
};
static struct platform_device hwt101_kim_device = {
    .name = "kim", .id = -1,
};
static struct platform_device hwt101_btwilink_device = {
    .name = "btwilink", .id = -1,
};
static struct wake_lock hwt101_st_wk_lock;

static struct i2c_board_info hwt101_i2c_bus0_devs[] = {
    { .type = "tpa2028_l", .addr = 0x58, .flags = 1, .platform_data = &tpa2028_l_pdata },
};

/* FIX10 calls i2c_register_board_info(1, ..., 10). Index 1 is a zero slot in
 * the OEM binary; retain it so the registration count and layout stay honest. */
static struct i2c_board_info hwt101_i2c_bus1_devs[] = {
    { .type = "sn65dsi83",          .addr = 0x2d, .flags = 1, .platform_data = &hwt101_sn65_pdata },
    { },
    { .type = "bq2419x_charger",    .addr = 0x6b, .irq = GPIO_0_5, .platform_data = &hwt101_bq2419x_pdata },
    { .type = "audience_es305",     .addr = 0x3e, .platform_data = &audience_platform_data },
    { .type = "atmel_mxt224e",      .addr = 0x4a },
    { .type = "mhl_Sii9244_page0",  .addr = 0x3b },
    { .type = "mhl_Sii9244_page1",  .addr = 0x3f },
    { .type = "mhl_Sii9244_page2",  .addr = 0x4b },
    { .type = "mhl_Sii9244_cbus",   .addr = 0x66 },
    { .type = "tpa2028_r",          .addr = 0x58, .flags = 1, .platform_data = &tpa2028_r_pdata },
};

static struct i2c_board_info hwt101_i2c_bus2_devs[] = {
    { .type = "ft5x0x_ts", .addr = 0x38, .irq = GPIO_19_5 },
    { .type = "Goodix-TS", .addr = 0x14, .irq = GPIO_19_5 },
};

'''
s = s[:pos] + inject + s[pos:]

# Replace the S10/U9508 platform list by the 21-entry list recovered from FIX10.
pat = re.compile(r'static struct platform_device \*k3v2oem1_public_dev\[\]\s+__initdata\s*=\s*\{.*?\n\};', re.S)
public = r'''static struct platform_device *k3v2oem1_public_dev[] __initdata = {
    &hisik3_hi6421_irq_device,       /* hi6421-irq */
    &hisik3_adc_device,              /* k3adc */
#ifdef CONFIG_LEDS_K3_6421
    &hi6421_led_device,              /* k3_leds */
#endif
#ifdef CONFIG_ANDROID_K3_VIBRATOR
    &hi6421_vibrator_device,         /* vibrator */
#endif
    &hisik3_camera_device,           /* k3-camera-v4l2 */
    &hisik3_fake_camera_device,      /* k3-fake-camera-v4l2 */
    &hisik3_device_hwmon,            /* k3-hwmon */
    &hisik3_gpio_keypad_device,      /* k3v2_gpio_key */
    &hisik3_keypad_device,           /* k3_keypad */
    &hisik3_keypad_backlight_device, /* keyboard-backlight */
    &k3_lcd_device,                  /* mipi_toshiba_MDW70_V001 */
    &k3_gps_bcm_device,              /* k3_gps_bcm_47511 */
    &hwt101_bq_bci_device,           /* bq_bci_battery */
    &hwt101_kim_device,              /* kim */
    &bcm_bluesleep_device,           /* bluesleep */
    &hwt101_btwilink_device,         /* btwilink */
    &hisik3_power_key_device,        /* k3v2_power_key */
    &tpa6132_device,                 /* tpa6132 */
    &usb_switch_device,              /* switch-usb */
    &boardid_dev,                    /* boardid_dev */
    &hisik3_watchdog_device,         /* k3v2_watchdog */
};'''
s, n = pat.subn(public, s, count=1)
if n != 1:
    raise SystemExit('ERROR: public device array not replaced')

# Replace I2C registration with the exact OEM 1/10/2 bus topology.
pat = re.compile(r'static void k3v2_i2c_devices_init\(void\)\s*\{.*?\n\}', re.S)
i2c_init = r'''static void k3v2_i2c_devices_init(void)
{
    i2c_register_board_info(0, hwt101_i2c_bus0_devs, ARRAY_SIZE(hwt101_i2c_bus0_devs));
    i2c_register_board_info(1, hwt101_i2c_bus1_devs, ARRAY_SIZE(hwt101_i2c_bus1_devs));
    i2c_register_board_info(2, hwt101_i2c_bus2_devs, ARRAY_SIZE(hwt101_i2c_bus2_devs));
}'''
s, n = pat.subn(i2c_init, s, count=1)
if n != 1:
    raise SystemExit('ERROR: i2c init not replaced')

# Replace board init. Preserve common init, board detection, TI-style wake lock,
# 21 platform registrations, recovered I2C topology and debugfs. No Synaptics
# virtual-key helper is called because the T101 uses FT5X0X/Goodix entries.
pat = re.compile(r'static void __init k3v2oem1_init\(void\)\s*\{.*?\n\}\s*\n\s*static void __init k3v2_early_init', re.S)
board_init = r'''static void __init k3v2oem1_init(void)
{
    unsigned int board_type;
    struct kobject *properties_kobj;

    edb_trace(1);
    k3v2_common_init();
    board_type = get_board_type();
    printk(KERN_INFO "HWT101 FIX10 parity board_type=%u\n", board_type);

    wake_lock_init(&hwt101_st_wk_lock, WAKE_LOCK_SUSPEND, "st_wake_lock");
    platform_add_devices(k3v2oem1_public_dev, ARRAY_SIZE(k3v2oem1_public_dev));
    k3v2_i2c_devices_init();

    properties_kobj = kobject_create_and_add("board_properties", NULL);
    if (!properties_kobj)
        pr_err("HWT101: failed to create board_properties\n");

#ifdef CONFIG_DEBUG_FS
    config_debugfs_init();
#endif
}

static void __init k3v2_early_init'''
s, n = pat.subn(board_init, s, count=1)
if n != 1:
    raise SystemExit('ERROR: board init not replaced')

p.write_text(s)
print('PATCHED', p)
print('HWT101 topology installed: platform=21, i2c=1/10/2, panel=Toshiba, sn65=0x2d gpio79')
