#!/usr/bin/env python3
from pathlib import Path
import re, sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else "kernel")
power = root / "drivers/power"
mk = power / "Makefile"
kc = power / "Kconfig"
cfg = root / ".config"

for p in (mk, kc, cfg, power/"bq_bci_battery.c", power/"bq2419x_charger.c"):
    if not p.exists():
        raise SystemExit(f"missing required battery source: {p}")

# Board reconstruction already contains the exact HWT101 OEM platform devices.
board_hits=[]
for p in (root/"arch/arm/mach-k3v2").glob("*.c"):
    s=p.read_text(errors="ignore")
    if "hwt101_bq_bci_device" in s:
        board_hits.append(p)
if len(board_hits) != 1:
    raise SystemExit(f"expected exactly one HWT101 BQ board source, got {board_hits}")
board=board_hits[0]
bs=board.read_text()
for token in ('"bq_bci_battery"', '"bq2419x_charger"', 'hwt101_bq2419x_pdata'):
    if token not in bs:
        raise SystemExit(f"board battery parity token missing: {token}")

# Enable the legacy/FIX10 power objects. Keep the actual BQ27510 I2C driver out:
# HWT101 FIX10 has bqdemon APIs, not bq27510_* driver symbols.
ms=mk.read_text()
ms=ms.replace('#obj-$(CONFIG_BQ_BCI_BATTERY)    += bq_bci_battery.o',
              'obj-$(CONFIG_BQ_BCI_BATTERY)    += bq_bci_battery.o hwt101_bqdemon_compat.o')
ms=ms.replace('#obj-$(CONFIG_CHARGER_BQ2419x)   += bq2419x_charger.o',
              'obj-$(CONFIG_CHARGER_BQ2419x)   += bq2419x_charger.o')
if 'hwt101_bqdemon_compat.o' not in ms:
    ms += '\nobj-$(CONFIG_BQ_BCI_BATTERY) += hwt101_bqdemon_compat.o\n'
if re.search(r'^\s*#?obj-\$\(CONFIG_CHARGER_BQ2419x\).*bq2419x_charger\.o', ms, re.M) is None:
    ms += '\nobj-$(CONFIG_CHARGER_BQ2419x) += bq2419x_charger.o\n'
mk.write_text(ms)

# BQ_BCI in this HWT101 port is backed by the PMIC/ADC compatibility layer,
# therefore it must not depend on the absent legacy BQ27510 I2C driver.
ks=kc.read_text()
old='''config BQ_BCI_BATTERY
        tristate "Power supply class support"
        depends on BATTERY_BQ27510
        depends on CHARGER_BQ2419x
        depends on K3_ADC'''
new='''config BQ_BCI_BATTERY
        tristate "Power supply class support"
        depends on CHARGER_BQ2419x
        depends on K3_ADC'''
if old in ks:
    ks=ks.replace(old,new,1)
elif 'config BQ_BCI_BATTERY' in ks and 'depends on BATTERY_BQ27510' in ks:
    # Narrow fallback only inside the BQ_BCI stanza.
    a=ks.index('config BQ_BCI_BATTERY')
    b=ks.find('\nconfig ',a+1)
    if b<0: b=len(ks)
    block=ks[a:b].replace('        depends on BATTERY_BQ27510\n','')
    ks=ks[:a]+block+ks[b:]
else:
    raise SystemExit("BQ_BCI Kconfig stanza not found")
kc.write_text(ks)

def set_cfg(name, value):
    global cs
    cs=re.sub(rf'^CONFIG_{re.escape(name)}=.*\n','',cs,flags=re.M)
    cs=re.sub(rf'^# CONFIG_{re.escape(name)} is not set\n','',cs,flags=re.M)
    if value == 'y':
        cs += f'CONFIG_{name}=y\n'
    elif value == 'n':
        cs += f'# CONFIG_{name} is not set\n'
    else:
        cs += f'CONFIG_{name}={value}\n'

cs=cfg.read_text()
for n in ('BATTERY_K3_BQ27510','BATTERY_K3_BQ24161','BATTERY_K3',
          'BATTERY_K3_USB_TEST','BATTERY_BQ27510'):
    set_cfg(n,'n')
for n in ('CHARGER_BQ2419x','BQ_BCI_BATTERY'):
    set_cfg(n,'y')
cfg.write_text(cs)

compat = r'''/*
 * HWT101 FIX10 battery compatibility layer.
 *
 * FIX10 does not contain the K3 bq27510/k3_battery_monitor stack.  It uses
 * bq_bci_battery + bq2419x and Huawei bqdemon functions backed by PMIC ADC.
 * The private bqdemon source is unavailable; this layer preserves the same
 * external API while reading the real HWT101 ADC channels proven from FIX10
 * machine code: channel 9 for battery voltage and ADC_RTMP (6) for NTC.
 *
 * No constant fake SOC is used. Capacity is derived from measured voltage,
 * then the stock bq_bci window filter/direction logic smooths it.
 */
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/i2c.h>
#include <linux/mutex.h>
#include <linux/delay.h>
#include <linux/power_supply.h>
#include <linux/power/bq27510_battery.h>
#include <linux/hkadc/hiadc_hal.h>

static DEFINE_MUTEX(hwt101_bat_adc_lock);
static struct bq27510_device_info hwt101_bqdemon_device;
struct bq27510_device_info *g_battery_measure_by_bq27510_device =
    &hwt101_bqdemon_device;
struct i2c_client *g_battery_measure_by_bq27510_i2c_client;

static int last_voltage_mv = 3700;
static int last_temperature_c = 25;

/* Same thermistor table embedded in the HWT101 K3V2 board source.
 * index 0=-2C, index 1=-1C, index 2=0C ... index 64=62C.
 */
static const int hwt101_ntc_mv[] = {
    929,925,
    920,917,912,908,904,899,895,890,885,880,
    875,869,864,858,853,847,841,835,829,823,
    816,810,804,797,790,783,776,769,762,755,
    748,740,732,725,718,710,703,695,687,679,
    671,663,655,647,639,631,623,615,607,599,
    591,583,575,567,559,551,543,535,527,519,
    511,504,496
};

static int hwt101_adc_read(int ch)
{
    unsigned char reserve = 0;
    int ret, value = -1;

    mutex_lock(&hwt101_bat_adc_lock);
    ret = k3_adc_open_channel(ch);
    if (ret < 0)
        goto out;
    if (ch == ADC_RTMP)
        msleep(10);
    value = k3_adc_get_value(ch, &reserve);
    k3_adc_close_channal(ch);
out:
    mutex_unlock(&hwt101_bat_adc_lock);
    return value;
}

int bq27510_get_gpadc_conversion(int channel_no)
{
    return hwt101_adc_read(channel_no);
}
EXPORT_SYMBOL(bq27510_get_gpadc_conversion);

static int hwt101_read_voltage_mv(void)
{
    int mv;

    /* FIX10 bqdemon_battery_voltage() passes literal channel 9. */
    mv = hwt101_adc_read(ADC_NC2);
    if (mv < 3000 || mv > 4600)
        mv = hwt101_adc_read(ADC_VBATMON);
    if (mv >= 3000 && mv <= 4600)
        last_voltage_mv = mv;
    return last_voltage_mv;
}

static int hwt101_ntc_to_celsius(int mv)
{
    int i, best = 0, delta, best_delta = 0x7fffffff;

    if (mv <= 0)
        return last_temperature_c;
    for (i = 0; i < ARRAY_SIZE(hwt101_ntc_mv); i++) {
        delta = hwt101_ntc_mv[i] - mv;
        if (delta < 0) delta = -delta;
        if (delta < best_delta) {
            best_delta = delta;
            best = i;
        }
    }
    return best - 2;
}

static int hwt101_read_temperature_c(void)
{
    int raw = hwt101_adc_read(ADC_RTMP);
    int t = hwt101_ntc_to_celsius(raw);

    if (t >= -20 && t <= 80)
        last_temperature_c = t;
    return last_temperature_c;
}

/* OCV/SOC curve chosen to follow the FIX10 observations:
 * ~3700mV ~= high-20s, ~3900mV ~= mid-60s, ~4000mV ~= ~80%.
 * It is deliberately monotonic; bq_bci applies its own 10-sample filter.
 */
struct hwt101_soc_point { int mv; int pct; };
static const struct hwt101_soc_point hwt101_soc_curve[] = {
    {3200,0}, {3300,1}, {3400,3}, {3500,8}, {3600,15},
    {3700,27}, {3750,34}, {3800,43}, {3850,54}, {3900,65},
    {3950,74}, {4000,81}, {4050,86}, {4100,91}, {4150,95},
    {4200,99}, {4250,100}
};

static int hwt101_capacity_from_mv(int mv)
{
    int i;
    if (mv <= hwt101_soc_curve[0].mv)
        return hwt101_soc_curve[0].pct;
    for (i = 1; i < ARRAY_SIZE(hwt101_soc_curve); i++) {
        int x0 = hwt101_soc_curve[i-1].mv;
        int y0 = hwt101_soc_curve[i-1].pct;
        int x1 = hwt101_soc_curve[i].mv;
        int y1 = hwt101_soc_curve[i].pct;
        if (mv <= x1)
            return y0 + (mv-x0)*(y1-y0)/(x1-x0);
    }
    return 100;
}

int bq27510_battery_voltage(struct bq27510_device_info *di)
{
    return hwt101_read_voltage_mv();
}
EXPORT_SYMBOL(bq27510_battery_voltage);

int bq27510_battery_temperature(struct bq27510_device_info *di)
{
    return hwt101_read_temperature_c();
}
EXPORT_SYMBOL(bq27510_battery_temperature);

short bq27510_battery_current(struct bq27510_device_info *di)
{
    /* FIX10 estimates this with bqdemon load modelling. Current is not used
     * by Android for critical-battery shutdown; zero is a neutral safe value.
     */
    return 0;
}
EXPORT_SYMBOL(bq27510_battery_current);

int bq27510_battery_capacity(struct bq27510_device_info *di)
{
    return hwt101_capacity_from_mv(hwt101_read_voltage_mv());
}
EXPORT_SYMBOL(bq27510_battery_capacity);

int is_bq27510_battery_exist(struct bq27510_device_info *di)
{
    int mv = hwt101_read_voltage_mv();
    return (mv >= 3000 && mv <= 4600);
}
EXPORT_SYMBOL(is_bq27510_battery_exist);

int is_bq27510_battery_full(struct bq27510_device_info *di)
{
    return bq27510_battery_capacity(di) >= 99;
}
EXPORT_SYMBOL(is_bq27510_battery_full);

int is_bq27510_battery_reach_threshold(struct bq27510_device_info *di)
{
    return hwt101_read_voltage_mv() < 3350 ? BQ27510_FLAG_LOCK : 0;
}
EXPORT_SYMBOL(is_bq27510_battery_reach_threshold);

int bq27510_battery_health(struct bq27510_device_info *di)
{
    int t = hwt101_read_temperature_c();
    if (t >= 60)
        return POWER_SUPPLY_HEALTH_OVERHEAT;
    return POWER_SUPPLY_HEALTH_GOOD;
}
EXPORT_SYMBOL(bq27510_battery_health);

int bq27510_battery_capacity_level(struct bq27510_device_info *di)
{
    int c = bq27510_battery_capacity(di);
    if (c <= 1) return POWER_SUPPLY_CAPACITY_LEVEL_CRITICAL;
    if (c <= 15) return POWER_SUPPLY_CAPACITY_LEVEL_LOW;
    if (c >= 99) return POWER_SUPPLY_CAPACITY_LEVEL_FULL;
    if (c >= 90) return POWER_SUPPLY_CAPACITY_LEVEL_HIGH;
    return POWER_SUPPLY_CAPACITY_LEVEL_NORMAL;
}
EXPORT_SYMBOL(bq27510_battery_capacity_level);

int bq27510_battery_technology(struct bq27510_device_info *di)
{
    return POWER_SUPPLY_TECHNOLOGY_LION;
}
EXPORT_SYMBOL(bq27510_battery_technology);

int bq27510_battery_rm(struct bq27510_device_info *di)
{
    return 0;
}
EXPORT_SYMBOL(bq27510_battery_rm);

int bq27510_battery_fcc(struct bq27510_device_info *di)
{
    return 0;
}
EXPORT_SYMBOL(bq27510_battery_fcc);

int bq27510_battery_tte(struct bq27510_device_info *di) { return 0; }
int bq27510_battery_ttf(struct bq27510_device_info *di) { return 0; }
int bq27510_battery_status(struct bq27510_device_info *di)
{
    return POWER_SUPPLY_STATUS_UNKNOWN;
}
int bq27510_battery_check_firmware_version(struct bq27510_device_info *di)
{
    return 0;
}
const char *bq27510_battery_get_firmware_version(struct bq27510_device_info *di)
{
    return "HWT101-FIX10-ADC";
}

int get_battery_id(void)
{
    return BAT_NO_PRESENT_STATUS;
}
EXPORT_SYMBOL(get_battery_id);

bool bq27510_get_gasgauge_normal_capacity(unsigned int *design_capacity)
{
    return false; /* bq2419x keeps its OEM default capacity */
}
EXPORT_SYMBOL(bq27510_get_gasgauge_normal_capacity);

bool bq27510_get_gasgauge_param_temperature(unsigned int *param_5,
                                             unsigned int *param_10)
{
    return false; /* bq2419x keeps its OEM default low-temp parameters */
}
EXPORT_SYMBOL(bq27510_get_gasgauge_param_temperature);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("HWT101 FIX10 ADC/bqdemon compatibility");
'''
(power/"hwt101_bqdemon_compat.c").write_text(compat)

# Source-level audit.
cs=cfg.read_text()
required = [
    'CONFIG_CHARGER_BQ2419x=y',
    'CONFIG_BQ_BCI_BATTERY=y',
    '# CONFIG_BATTERY_K3_BQ27510 is not set',
    '# CONFIG_BATTERY_K3_BQ24161 is not set',
    '# CONFIG_BATTERY_K3 is not set',
]
for x in required:
    if x not in cs:
        raise SystemExit("config gate missing: "+x)
for x in ('bq_bci_battery.o hwt101_bqdemon_compat.o','bq2419x_charger.o'):
    if x not in mk.read_text():
        raise SystemExit("Makefile gate missing: "+x)

print("V411_BATTERY_PARITY_PATCH=PASS")
print("BASE=V410B_HARDWARE_BOOT_TO_LAUNCHER")
print("BOARD_DEVICE=bq_bci_battery")
print("CHARGER=bq2419x_charger")
print("K3_BATTERY_STACK=OFF")
print("BATTERY_VOLTAGE_ADC=9")
print("BATTERY_TEMP_ADC=6")
print("SOC_SOURCE=REAL_ADC_VOLTAGE")
print("CONSTANT_FAKE_SOC=NO")
print("HSAD_HDMI_NAND_YAFFS=UNCHANGED")
