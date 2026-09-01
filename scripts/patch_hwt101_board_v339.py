#!/usr/bin/env python3
from pathlib import Path
import re, sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch_hwt101_board_v339.py <kernel-root>')
K=Path(sys.argv[1])
board=K/'arch/arm/mach-k3v2/board-k3v2oem1.c'
s=board.read_text()

# OEM FIX10 regulator table: LDO17 has two consumers in this exact role:
#   k3_dev_lcd -> lcdanalog-vcc
#   sn65dsi83  -> lcd-vcc
reg=K/'arch/arm/mach-k3v2/include/mach/board-hi6421-regulator.h'
rs=reg.read_text()
needle='static struct regulator_consumer_supply ldo17_consumers[] = {\n\tREGULATOR_SUPPLY("lcdanalog-vcc", "k3_dev_lcd"),\n};'
replacement_reg='static struct regulator_consumer_supply ldo17_consumers[] = {\n\tREGULATOR_SUPPLY("lcdanalog-vcc", "k3_dev_lcd"),\n\tREGULATOR_SUPPLY("lcd-vcc", "sn65dsi83"),\n};'
if needle not in rs and 'REGULATOR_SUPPLY("lcd-vcc", "sn65dsi83")' not in rs:
    raise SystemExit('unexpected LDO17 layout; refusing blind regulator patch')
if needle in rs:
    rs=rs.replace(needle,replacement_reg)
reg.write_text(rs)

# Replace only the late board-registration block. Common SoC/clock/PMIC data is kept.
start=s.index('/* please add platform device in the struct.*/')
end=s.index('static void __init k3v2oem1_init(void)', start)
replacement=r'''/* HWT101 / MS1211 early-boot board registration recovered from FIX10.
 * Keep only devices required to reach Android; secondary peripherals are added
 * only after this baseline is proven on hardware. */
struct hwt101_sn65dsi83_platform_data {
    int en_gpio;
};

static struct hwt101_sn65dsi83_platform_data hwt101_sn65_pdata = {
    .en_gpio = 79,
};

static struct i2c_board_info hwt101_i2c_bus1_devs[] = {
    {
        .type = "sn65dsi83",
        .addr = 0x2d,
        .flags = true,
        .platform_data = &hwt101_sn65_pdata,
    },
};

static struct platform_device *k3v2oem1_public_dev[] __initdata = {
    &hisik3_hi6421_irq_device,
    &hisik3_adc_device,
#ifdef CONFIG_LEDS_K3_6421
    &hi6421_led_device,
#endif
#ifdef CONFIG_ANDROID_K3_VIBRATOR
    &hi6421_vibrator_device,
#endif
    &hisik3_gpio_keypad_device,
    &hisik3_keypad_backlight_device,
    &k3_lcd_device,
    &hisik3_power_key_device,
    &tpa6132_device,
    &usb_switch_device,
    &boardid_dev,
    &hisik3_watchdog_device,
};

static void k3v2_i2c_devices_init(void)
{
    /* OEM FIX10: bus0 has left TPA2028. */
    i2c_register_board_info(0, hisik3_i2c_bus0_devs,
                            ARRAY_SIZE(hisik3_i2c_bus0_devs));
    /* Boot-critical HWT101 bridge. Do not register S10 charger/BT/touch data. */
    i2c_register_board_info(1, hwt101_i2c_bus1_devs,
                            ARRAY_SIZE(hwt101_i2c_bus1_devs));
}

'''
s=s[:start]+replacement+s[end:]

# OEM init does not call Synaptics virtual-key setup.
s=s.replace('\n\tsynaptics_virtual_keys_init();\n','\n')
board.write_text(s)

# Install reconstructed OEM-behaviour SN65 driver into K3 display build.
src=Path('oem_recovered/display/sn65dsi83_hwt101.c')
tab=Path('oem_recovered/display/sn65dsi83_oem_table.h')
if not src.exists() or not tab.exists():
    raise SystemExit('missing recovered SN65 source/table in workflow checkout')
dst=K/'drivers/video/k3'
(dst/'sn65dsi83_hwt101.c').write_text(src.read_text())
(dst/'sn65dsi83_oem_table.h').write_text(tab.read_text())
mk=dst/'Makefile'
ms=mk.read_text()
line='obj-y += sn65dsi83_hwt101.o\n'
if line not in ms:
    ms += '\n# HWT101 MS1211 display bridge recovered from FIX10\n'+line
mk.write_text(ms)

# Install neutral providers for Huawei globals referenced by common code when
# secondary battery/touch drivers are intentionally absent from first boot.
helper=Path('scripts/add_hwt101_boot_abi.py')
if not helper.exists():
    raise SystemExit('missing scripts/add_hwt101_boot_abi.py')
exec(compile(helper.read_text(), str(helper), 'exec'), {'__name__':'__main__', '__file__':str(helper)})

# Hard assertions.
patched=board.read_text()
block=patched[patched.index('static struct platform_device *k3v2oem1_public_dev'):patched.index('static void __init k3v2oem1_init')]
for bad in ('btbcm_device','bcm_bluesleep_device','modem_switch_device','hisik3_battery_monitor'):
    if bad in block:
        raise SystemExit('forbidden S10/public early device remains: '+bad)
for good in ('k3_lcd_device','usb_switch_device','hisik3_watchdog_device','sn65dsi83','0x2d'):
    if good not in block:
        raise SystemExit('required HWT101 board item missing: '+good)
if 'REGULATOR_SUPPLY("lcd-vcc", "sn65dsi83")' not in reg.read_text():
    raise SystemExit('OEM SN65 LDO17 supply missing')
print('HWT101 V3.39 board isolation + OEM LDO17 SN65 supply + neutral ABI: OK')
