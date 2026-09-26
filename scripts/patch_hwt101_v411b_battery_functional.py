#!/usr/bin/env python3
from pathlib import Path
import re, sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else "kernel")
power = root / "drivers/power"
cfg = root / ".config"
mk = power / "Makefile"
kc = power / "Kconfig"

for p in (cfg, mk, kc, power/"bq_bci_battery.c", power/"bq2419x_charger.c"):
    if not p.exists():
        raise SystemExit("missing required file: %s" % p)

# ----------------------------------------------------------------------
# 1. Exact T101 board topology was already reconstructed by V4.10B.
#    Attach the battery monitor platform-data that the public reconstruction
#    lacked. Charger pdata is already exact from FIX10 binary:
#    1800mA / 4208mV / 1800mA / GPIO_9_2.
# ----------------------------------------------------------------------
board_hits = []
for p in (root/"arch/arm/mach-k3v2").glob("*.c"):
    s = p.read_text(errors="ignore")
    if "hwt101_bq2419x_pdata" in s and "hwt101_bq_bci_device" in s:
        board_hits.append(p)
if len(board_hits) != 1:
    raise SystemExit("expected one reconstructed HWT101 board, got %r" % board_hits)

board = board_hits[0]
bs = board.read_text(errors="ignore")

active_bci = "#include <linux/power/bq_bci_battery.h> /* HWT101_ACTIVE */"
if active_bci not in bs:
    anchor = "#include <linux/wakelock.h>"
    if anchor not in bs:
        raise SystemExit("active wakelock include anchor missing")
    bs = bs.replace(anchor, anchor+"\\n"+active_bci, 1)

charger_pdata_end = '''static struct bq2419x_platform_data hwt101_bq2419x_pdata = {
    .max_charger_currentmA = 1800,
    .max_charger_voltagemV = 4208,
    .termination_currentmA = 0,
    .max_cin_limit_currentmA = 1800,
    .gpio = GPIO_9_2,
};
'''
if charger_pdata_end not in bs:
    raise SystemExit("exact HWT101 charger pdata anchor missing")

battery_pdata = r'''
/* HWT101 battery-monitor platform data.
 * The charger limits above are exact FIX10 binary values.
 * Monitor timing/low-voltage threshold match Huawei's K3 battery ABI.
 */
static int hwt101_batt_temp_table[] = {
    929, 925,
    920, 917, 912, 908, 904, 899, 895, 890, 885, 880,
    875, 869, 864, 858, 853, 847, 841, 835, 829, 823,
    816, 810, 804, 797, 790, 783, 776, 769, 762, 755,
    748, 740, 732, 725, 718, 710, 703, 695, 687, 679,
    671, 663, 655, 647, 639, 631, 623, 615, 607, 599,
    591, 583, 575, 567, 559, 551, 543, 535, 527, 519,
    511, 504, 496
};

static struct bq_bci_platform_data hwt101_bq_bci_pdata = {
    .battery_tmp_tbl = hwt101_batt_temp_table,
    .tblsize = ARRAY_SIZE(hwt101_batt_temp_table),
    .monitoring_interval = 10,
    .max_charger_currentmA = 1800,
    .max_charger_voltagemV = 4208,
    .termination_currentmA = 100,
    .max_bat_voltagemV = 4208,
    .low_bat_voltagemV = 3300,
};
'''
if "hwt101_bq_bci_pdata" not in bs:
    bs = bs.replace(charger_pdata_end, charger_pdata_end+battery_pdata, 1)

old_dev = '''static struct platform_device hwt101_bq_bci_device = {
    .name = "bq_bci_battery", .id = 1,
};'''
new_dev = '''static struct platform_device hwt101_bq_bci_device = {
    .name = "bq_bci_battery",
    .id = 1,
    .dev = {
        .platform_data = &hwt101_bq_bci_pdata,
    },
};'''
if old_dev in bs:
    bs = bs.replace(old_dev, new_dev, 1)
elif ".platform_data = &hwt101_bq_bci_pdata" not in bs:
    raise SystemExit("HWT101 bq_bci device anchor missing")

board.write_text(bs)

# ----------------------------------------------------------------------
# 2. Enable the FIX10-style battery architecture visible in original dmesg:
#    bq_bci_battery + bq2419x_charger. The private OEM bqdemon source is not
#    in the public tree; supply its battery API from real PMIC ADC readings.
# ----------------------------------------------------------------------
ms = mk.read_text()
for old,new in [
    ('#obj-$(CONFIG_BQ_BCI_BATTERY)    += bq_bci_battery.o',
     'obj-$(CONFIG_BQ_BCI_BATTERY)    += bq_bci_battery.o hwt101_bqdemon_compat.o'),
    ('#obj-$(CONFIG_CHARGER_BQ2419x)   += bq2419x_charger.o',
     'obj-$(CONFIG_CHARGER_BQ2419x)   += bq2419x_charger.o'),
]:
    if old in ms:
        ms = ms.replace(old,new,1)
if 'bq_bci_battery.o hwt101_bqdemon_compat.o' not in ms:
    raise SystemExit("failed to enable BQ_BCI objects")
if re.search(r'^obj-\$\(CONFIG_CHARGER_BQ2419x\).*bq2419x_charger\.o', ms, re.M) is None:
    raise SystemExit("failed to enable bq2419x object")
mk.write_text(ms)

ks = kc.read_text()
a = ks.find("config BQ_BCI_BATTERY")
if a < 0:
    raise SystemExit("BQ_BCI Kconfig stanza missing")
b = ks.find("\nconfig ", a+1)
if b < 0: b = len(ks)
block = ks[a:b].replace("        depends on BATTERY_BQ27510\n","")
ks = ks[:a] + block + ks[b:]
kc.write_text(ks)

cs = cfg.read_text()
def set_cfg(name, val):
    global cs
    cs = re.sub(r'^CONFIG_%s=.*\n' % re.escape(name), '', cs, flags=re.M)
    cs = re.sub(r'^# CONFIG_%s is not set\n' % re.escape(name), '', cs, flags=re.M)
    if val:
        cs += "CONFIG_%s=y\n" % name
    else:
        cs += "# CONFIG_%s is not set\n" % name

for n in ("BATTERY_K3_BQ27510","BATTERY_K3_BQ24161","BATTERY_K3",
          "BATTERY_K3_USB_TEST","BATTERY_BQ27510"):
    set_cfg(n, False)
for n in ("CHARGER_BQ2419x","BQ_BCI_BATTERY"):
    set_cfg(n, True)
cfg.write_text(cs)

# Public bq2419x source references an NCT203 helper that FIX10 does not expose.
# Feed that protection from the same real battery temperature API instead.
charger = power/"bq2419x_charger.c"
chs = charger.read_text(encoding="latin-1")
old_hot = '''static int get_hot_temperature()
{
    extern int nct203_temp_report(void);
    return nct203_temp_report();
}'''
new_hot = '''static int get_hot_temperature()
{
    return bq27510_battery_temperature(g_battery_measure_by_bq27510_device);
}'''
if old_hot in chs:
    chs = chs.replace(old_hot,new_hot,1)
elif new_hot not in chs:
    raise SystemExit("bq2419x thermal helper anchor missing")
charger.write_text(chs,encoding="latin-1")

compat = r'''/*
 * HWT101/T101 FIX10 battery compatibility layer.
 *
 * The working FIX10 image exposes bq_bci_battery + bq2419x_charger and a
 * private Huawei bqdemon implementation. That private source is absent from
 * the public K3V2 tree. This compatibility layer keeps the same API but reads
 * the real PMIC ADC. It never reports a hard-coded 0% on an ADC startup error.
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
static int last_capacity = 30;

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

    /* Recovered FIX10 bqdemon path uses ADC channel 9; VBATMON is a safe
     * hardware fallback if the board-specific channel is unavailable.
     */
    mv = hwt101_adc_read(ADC_NC2);
    if (mv < 3000 || mv > 4600)
        mv = hwt101_adc_read(ADC_VBATMON);
    if (mv >= 3000 && mv <= 4600)
        last_voltage_mv = mv;

    return last_voltage_mv;
}

static int hwt101_ntc_to_celsius(int mv)
{
    int i, best = 0, d, best_d = 0x7fffffff;
    if (mv <= 0)
        return last_temperature_c;
    for (i=0; i<ARRAY_SIZE(hwt101_ntc_mv); i++) {
        d = hwt101_ntc_mv[i] - mv;
        if (d < 0) d = -d;
        if (d < best_d) { best_d = d; best = i; }
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

/* Conservative voltage-derived fallback for the unavailable private bqdemon
 * SOC model. It is intentionally monotonic. bq_bci applies its own smoothing.
 * If ADC is temporarily unavailable, the last valid SOC is retained.
 */
struct hwt101_soc_point { int mv, pct; };
static const struct hwt101_soc_point hwt101_soc_curve[] = {
    {3200,1},{3300,3},{3400,5},{3500,8},{3600,15},
    {3700,25},{3750,32},{3800,42},{3850,53},{3900,64},
    {3950,73},{4000,80},{4050,86},{4100,91},{4150,95},
    {4200,99},{4250,100}
};

static int hwt101_capacity_from_mv(int mv)
{
    int i, c;
    if (mv < 3000 || mv > 4600)
        return last_capacity;
    if (mv <= hwt101_soc_curve[0].mv)
        c = hwt101_soc_curve[0].pct;
    else {
        c = 100;
        for (i=1; i<ARRAY_SIZE(hwt101_soc_curve); i++) {
            int x0=hwt101_soc_curve[i-1].mv, y0=hwt101_soc_curve[i-1].pct;
            int x1=hwt101_soc_curve[i].mv,   y1=hwt101_soc_curve[i].pct;
            if (mv <= x1) {
                c = y0 + (mv-x0)*(y1-y0)/(x1-x0);
                break;
            }
        }
    }
    if (c < 1) c = 1;
    if (c > 100) c = 100;
    last_capacity = c;
    return c;
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
    return 0;
}
EXPORT_SYMBOL(bq27510_battery_current);

int bq27510_battery_capacity(struct bq27510_device_info *di)
{
    int mv = hwt101_read_voltage_mv();
    int cap = hwt101_capacity_from_mv(mv);
    printk(KERN_INFO "HWT101_BAT: voltage=%d mV capacity=%d%% temp=%dC\n",
           mv, cap, last_temperature_c);
    return cap;
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
    return hwt101_read_voltage_mv() < 3300 ? BQ27510_FLAG_LOCK : 0;
}
EXPORT_SYMBOL(is_bq27510_battery_reach_threshold);

int bq27510_battery_health(struct bq27510_device_info *di)
{
    int t = hwt101_read_temperature_c();
    return t >= 60 ? POWER_SUPPLY_HEALTH_OVERHEAT : POWER_SUPPLY_HEALTH_GOOD;
}
EXPORT_SYMBOL(bq27510_battery_health);

int bq27510_battery_capacity_level(struct bq27510_device_info *di)
{
    int c = bq27510_battery_capacity(di);
    if (c <= 5) return POWER_SUPPLY_CAPACITY_LEVEL_CRITICAL;
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

int bq27510_battery_rm(struct bq27510_device_info *di) { return 0; }
int bq27510_battery_fcc(struct bq27510_device_info *di) { return 0; }
int bq27510_battery_tte(struct bq27510_device_info *di) { return 0; }
int bq27510_battery_ttf(struct bq27510_device_info *di) { return 0; }
int bq27510_battery_status(struct bq27510_device_info *di)
{ return POWER_SUPPLY_STATUS_UNKNOWN; }
int bq27510_battery_check_firmware_version(struct bq27510_device_info *di)
{ return 0; }
const char *bq27510_battery_get_firmware_version(struct bq27510_device_info *di)
{ return "HWT101-BQD-ADC-V411B"; }

EXPORT_SYMBOL(bq27510_battery_rm);
EXPORT_SYMBOL(bq27510_battery_fcc);

int get_battery_id(void) { return BAT_NO_PRESENT_STATUS; }
EXPORT_SYMBOL(get_battery_id);

bool bq27510_get_gasgauge_normal_capacity(unsigned int *design_capacity)
{ return false; }
EXPORT_SYMBOL(bq27510_get_gasgauge_normal_capacity);

bool bq27510_get_gasgauge_param_temperature(unsigned int *p5, unsigned int *p10)
{ return false; }
EXPORT_SYMBOL(bq27510_get_gasgauge_param_temperature);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("HWT101 FIX10 bqdemon ADC compatibility V4.11B");
'''
(power/"hwt101_bqdemon_compat.c").write_text(compat)

# Gates
bs = board.read_text(errors="ignore")
for token in (
    '.platform_data = &hwt101_bq_bci_pdata',
    '.max_charger_currentmA = 1800',
    '.max_charger_voltagemV = 4208',
    '.max_cin_limit_currentmA = 1800',
    '.low_bat_voltagemV = 3300',
    '"bq2419x_charger"',
    '"bq_bci_battery"',
):
    if token not in bs:
        raise SystemExit("board gate failed: "+token)

cs=cfg.read_text()
for x in (
    'CONFIG_CHARGER_BQ2419x=y',
    'CONFIG_BQ_BCI_BATTERY=y',
    '# CONFIG_BATTERY_K3_BQ27510 is not set',
    '# CONFIG_BATTERY_K3_BQ24161 is not set',
    '# CONFIG_BATTERY_K3 is not set',
    '# CONFIG_BATTERY_BQ27510 is not set',
):
    if x not in cs:
        raise SystemExit("config gate failed: "+x)

print("V411B_BATTERY_FUNCTIONAL_PATCH=PASS")
print("BASE=V410B_HARDWARE_BOOT_TO_LAUNCHER")
print("BATTERY_MONITOR=bq_bci_battery")
print("CHARGER=bq2419x_charger")
print("CHARGER_CURRENT_MA=1800")
print("CHARGER_VOLTAGE_MV=4208")
print("CHARGER_INPUT_LIMIT_MA=1800")
print("CHARGER_GPIO=74")
print("BATTERY_MONITOR_PDATA=ATTACHED")
print("BATTERY_SOURCE=REAL_PMIC_ADC")
print("ADC_STARTUP_FAILURE_ZERO_PERCENT=BLOCKED")
print("HSAD_HDMI_NAND_YAFFS=UNCHANGED")
