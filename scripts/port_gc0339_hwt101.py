#!/usr/bin/env python3
from pathlib import Path
import struct
import sys


def fail(msg):
    raise SystemExit('ERROR: ' + msg)


def find_blob(repo_root: Path, name: str) -> Path:
    candidates = [
        repo_root / 'oem_recovered' / 'camera' / name,
        repo_root.parent / 'oem_recovered' / 'camera' / name,
        Path('oem_recovered') / 'camera' / name,
    ]
    for p in candidates:
        if p.is_file():
            return p
    fail('missing recovered OEM blob: ' + name)


def c_init_array(blob: bytes) -> str:
    if len(blob) != 888 or len(blob) % 12:
        fail('gc0339_init_blob.bin must be exactly 888 bytes / 74 entries')
    rows = []
    for i in range(0, len(blob), 12):
        ch = blob[i:i+12]
        reg = struct.unpack_from('<I', ch, 0)[0] & 0xffff
        value = struct.unpack_from('<I', ch, 4)[0] & 0xffff
        mask = ch[8]
        rows.append('    { 0x%04x, 0x%04x, 0x%02x },' % (reg, value, mask))
    return '\n'.join(rows)


def c_isp_array(blob: bytes) -> str:
    if len(blob) != 5872 or len(blob) % 8:
        fail('gc0339_isp_blob.bin must be exactly 5872 bytes / 734 entries')
    rows = []
    for i in range(0, len(blob), 8):
        ch = blob[i:i+8]
        subaddr = struct.unpack_from('<I', ch, 0)[0]
        value = ch[4]
        mask = ch[5]
        rows.append('    { 0x%08x, 0x%02x, 0x%02x },' % (subaddr, value, mask))
    return '\n'.join(rows)


def patch_makefile(makefile: Path):
    text = makefile.read_text()
    marker = 'obj-$(CONFIG_VIDEO_HIK3_CAMERA) += gc0339/'
    if marker not in text:
        text = text.rstrip() + '\n\n# HWT101 OEM-behavior GC0339 reconstruction\n' + marker + '\n'
        makefile.write_text(text)


def main():
    if len(sys.argv) != 2:
        fail('usage: port_gc0339_hwt101.py <kernel-tree>')
    root = Path(sys.argv[1]).resolve()
    if not (root / 'drivers/media/video/hik3/capture').is_dir():
        fail('not an S10 HiK3 camera kernel tree: ' + str(root))

    init_blob = find_blob(root, 'gc0339_init_blob.bin').read_bytes()
    isp_blob = find_blob(root, 'gc0339_isp_blob.bin').read_bytes()
    init_rows = c_init_array(init_blob)
    isp_rows = c_isp_array(isp_blob)

    outdir = root / 'drivers/media/video/hik3/capture/gc0339'
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / 'Makefile').write_text('obj-y += gc0339.o\n')

    src = r'''/*
 * HWT101 GC0339 K3V2 camera reconstruction.
 *
 * NOT claimed to be Huawei original source. Power sequence, chip check,
 * I2C identity, sensor init stream and ISP stream are reconstructed from
 * recovered HWT101 OEM bytes/disassembly. Glue uses the S10 K3 camera API.
 */
#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/delay.h>
#include <linux/string.h>
#include <linux/videodev2.h>

#include "../isp/sensor_common.h"
#include "../isp/k3_isp_io.h"

#define GC0339_I2C_ADDR       0x42
#define GC0339_CHIP_ID_REG    0x00
#define GC0339_CHIP_ID        0xc8
#define GC0339_PAGE_REG       0xfc
#define GC0339_PAGE_VALUE     0x10
#define GC0339_INIT_COUNT     74
#define GC0339_ISP_COUNT      734
#define GC0339_WIDTH          640
#define GC0339_HEIGHT         480
#define GC0339_SKIP_FRAMES    3

struct gc0339_oem_init_entry {
    u16 reg;
    u16 value;
    u8 mask;
};

static const struct gc0339_oem_init_entry gc0339_init_regs[GC0339_INIT_COUNT] = {
@@INIT@@
};

static const struct isp_reg_t isp_init_regs_gc0339[GC0339_ISP_COUNT] = {
@@ISP@@
};

static camera_sensor gc0339_sensor;
static bool gc0339_sensor_inited;

static framesize_s gc0339_framesizes[] = {
    {
        .left = 0, .top = 0,
        .width = GC0339_WIDTH, .height = GC0339_HEIGHT,
        .fps = 30, .fps_es = 30,
        .view_type = VIEW_FULL,
        .resolution_type = RESOLUTION_4_3,
        .binning = false,
        .sensor_setting = { .setting = NULL, .seq_size = 0 },
    },
};

static int gc0339_read_reg(u16 reg, u16 *val)
{
    return k3_ispio_read_reg(gc0339_sensor.i2c_config.index,
                             (u8)gc0339_sensor.i2c_config.addr,
                             reg, val, I2C_8BIT);
}

static int gc0339_write_reg(u16 reg, u16 val, u8 mask)
{
    return k3_ispio_write_reg(gc0339_sensor.i2c_config.index,
                              (u8)gc0339_sensor.i2c_config.addr,
                              reg, val, I2C_8BIT, mask);
}

static int gc0339_get_format(struct v4l2_fmtdesc *fmt)
{
    if (!fmt) return -EINVAL;
    fmt->pixelformat = V4L2_PIX_FMT_YUYV;
    return 0;
}

static int gc0339_enum_frame_intervals(struct v4l2_frmivalenum *fi)
{
    if (!fi || fi->index > 0) return -EINVAL;
    fi->type = V4L2_FRMIVAL_TYPE_DISCRETE;
    fi->discrete.numerator = 1;
    fi->discrete.denominator = 30;
    return 0;
}

static int gc0339_enum_framesizes(struct v4l2_frmsizeenum *fs)
{
    if (!fs || fs->index > 0) return -EINVAL;
    fs->type = V4L2_FRMSIZE_TYPE_DISCRETE;
    fs->discrete.width = GC0339_WIDTH;
    fs->discrete.height = GC0339_HEIGHT;
    return 0;
}

static int gc0339_try_framesizes(struct v4l2_frmsizeenum *fs)
{
    if (!fs) return -EINVAL;
    if (fs->discrete.width > GC0339_WIDTH || fs->discrete.height > GC0339_HEIGHT)
        return -EINVAL;
    return 0;
}

static int gc0339_set_framesizes(camera_state state,
        struct v4l2_frmsize_discrete *fs, int flag,
        camera_setting_view_type view_type)
{
    (void)flag; (void)view_type;
    if (!fs || fs->width > GC0339_WIDTH || fs->height > GC0339_HEIGHT)
        return -EINVAL;
    if (state == STATE_PREVIEW)
        gc0339_sensor.preview_frmsize_index = 0;
    else
        gc0339_sensor.capture_frmsize_index = 0;
    fs->width = GC0339_WIDTH;
    fs->height = GC0339_HEIGHT;
    return 0;
}

static int gc0339_get_framesizes(camera_state state,
        struct v4l2_frmsize_discrete *fs)
{
    (void)state;
    if (!fs) return -EINVAL;
    fs->width = GC0339_WIDTH;
    fs->height = GC0339_HEIGHT;
    return 0;
}

static int gc0339_get_capability(u32 id, u32 *value)
{
    (void)id;
    if (!value) return -EINVAL;
    *value = 0;
    return 0;
}

static int gc0339_set_hflip(int flip) { gc0339_sensor.hflip = !!flip; return 0; }
static int gc0339_get_hflip(void) { return gc0339_sensor.hflip; }
static int gc0339_set_vflip(int flip) { gc0339_sensor.vflip = !!flip; return 0; }
static int gc0339_get_vflip(void) { return gc0339_sensor.vflip; }

static int gc0339_update_flip(u16 width, u16 height)
{
    u8 new_flip = (gc0339_sensor.vflip << 1) | gc0339_sensor.hflip;
    u8 changed = gc0339_sensor.old_flip ^ new_flip;
    if (changed) {
        k3_ispio_update_flip(changed, width, height, PIXEL_ORDER_CHANGED);
        gc0339_sensor.old_flip = new_flip;
    }
    return 0;
}

static u32 gc0339_get_gain(void) { return 0; }
static u32 gc0339_get_exposure(void) { return 0; }
static void gc0339_set_gain(u32 gain) { (void)gain; }
static void gc0339_set_exposure(u32 exposure) { (void)exposure; }
static void gc0339_set_effect(camera_effects effect) { (void)effect; }
static void gc0339_set_awb(camera_white_balance awb_mode) { (void)awb_mode; }

/* OEM: write 0xfc=0x10, read page, read ID 0x00, retry 3x/50ms,
 * require 0xc8, then load exactly 734 recovered ISP entries. */
static int gc0339_check_sensor(void)
{
    u16 page = 0, id = 0;
    int retry, ret;

    for (retry = 0; retry < 3; ++retry) {
        ret = gc0339_write_reg(GC0339_PAGE_REG, GC0339_PAGE_VALUE, 0);
        if (!ret) {
            gc0339_read_reg(GC0339_PAGE_REG, &page);
            ret = gc0339_read_reg(GC0339_CHIP_ID_REG, &id);
            if (!ret && ((u8)id == GC0339_CHIP_ID)) {
                k3_ispio_write_isp_seq(isp_init_regs_gc0339, GC0339_ISP_COUNT);
                return 0;
            }
        }
        msleep(50);
    }
    printk(KERN_ERR "gc0339: chip check failed id=0x%02x page=0x%02x\n",
           (u8)id, (u8)page);
    return -EFAULT;
}

/* Exact recovered 74-entry OEM init_reg loop semantics. */
static int gc0339_init_reg(void)
{
    unsigned int i;
    int ret;

    for (i = 0; i < GC0339_INIT_COUNT; ++i) {
        if (gc0339_init_regs[i].reg == 0) {
            msleep(gc0339_init_regs[i].value);
            continue;
        }
        ret = gc0339_write_reg(gc0339_init_regs[i].reg,
                               gc0339_init_regs[i].value,
                               gc0339_init_regs[i].mask);
        if (ret) return ret;
    }

    ret = k3_ispio_init_csi(gc0339_sensor.mipi_index,
                            gc0339_sensor.mipi_lane_count,
                            gc0339_sensor.lane_clk);
    if (ret) return -EFAULT;
    msleep(100);
    msleep(800);
    gc0339_sensor_inited = true;
    gc0339_set_awb(CAMERA_WHITEBALANCE_AUTO);
    return 0;
}

static int gc0339_stream_on(camera_state state)
{
    (void)state;
    /* Recovered framesize symbol was an alias to an ASCII string, so no
     * unproven register stream is invented here. Sensor/ISP init is exact. */
    return gc0339_update_flip(GC0339_WIDTH, GC0339_HEIGHT);
}

static int gc0339_reset(camera_power_state power_state)
{
    if (power_state == POWER_ON) {
        k3_isp_io_enable_mclk(MCLK_ENABLE, gc0339_sensor.sensor_index);
        k3_ispgpio_reset_sensor(gc0339_sensor.sensor_index, POWER_ON,
                                gc0339_sensor.power_conf.reset_valid);
    } else {
        k3_ispgpio_reset_sensor(gc0339_sensor.sensor_index, POWER_OFF,
                                gc0339_sensor.power_conf.reset_valid);
        k3_isp_io_enable_mclk(MCLK_DISABLE, gc0339_sensor.sensor_index);
    }
    return 0;
}

static void gc0339_shut_down(void)
{
    k3_ispgpio_power_sensor(&gc0339_sensor, POWER_OFF);
}

static int gc0339_init(void)
{
    if (gc0339_sensor.owner && !try_module_get(gc0339_sensor.owner))
        return -ENOENT;
    k3_ispio_power_init("pri-cameralog-vcc", 2850000, 2850000);
    k3_ispio_power_init("camera-vcc", 1800000, 1800000);
    k3_ispio_power_init("sec-cameralog-vcc", 2850000, 2850000);
    return 0;
}

static void gc0339_exit(void)
{
    k3_ispio_power_deinit();
    if (gc0339_sensor.owner) module_put(gc0339_sensor.owner);
}

static int gc0339_power(camera_power_state power)
{
    int ret = 0;
    if (power == POWER_ON) {
        k3_ispldo_power_sensor(power, "camera-vcc");
        k3_ispldo_power_sensor(power, "pri-cameralog-vcc");
        ret = camera_power_core_ldo(power);
        k3_ispgpio_power_sensor(&gc0339_sensor, power);
        msleep(200);
        k3_ispio_ioconfig(&gc0339_sensor, power);
        k3_ispldo_power_sensor(power, "sec-cameralog-vcc");
    } else {
        k3_ispio_deinit_csi(gc0339_sensor.mipi_index);
        k3_ispldo_power_sensor(power, "sec-cameralog-vcc");
        k3_ispgpio_power_sensor(&gc0339_sensor, power);
        k3_ispio_ioconfig(&gc0339_sensor, power);
        camera_power_core_ldo(power);
        k3_ispldo_power_sensor(power, "pri-cameralog-vcc");
        k3_ispldo_power_sensor(power, "camera-vcc");
        gc0339_sensor_inited = false;
    }
    return ret;
}

static void gc0339_set_default(void)
{
    memset(&gc0339_sensor, 0, sizeof(gc0339_sensor));
    gc0339_sensor.init = gc0339_init;
    gc0339_sensor.exit = gc0339_exit;
    gc0339_sensor.shut_down = gc0339_shut_down;
    gc0339_sensor.reset = gc0339_reset;
    gc0339_sensor.power = gc0339_power;
    gc0339_sensor.check_sensor = gc0339_check_sensor;
    gc0339_sensor.init_reg = gc0339_init_reg;
    gc0339_sensor.stream_on = gc0339_stream_on;
    gc0339_sensor.get_format = gc0339_get_format;
    gc0339_sensor.enum_framesizes = gc0339_enum_framesizes;
    gc0339_sensor.try_framesizes = gc0339_try_framesizes;
    gc0339_sensor.set_framesizes = gc0339_set_framesizes;
    gc0339_sensor.get_framesizes = gc0339_get_framesizes;
    gc0339_sensor.enum_frame_intervals = gc0339_enum_frame_intervals;
    gc0339_sensor.get_capability = gc0339_get_capability;
    gc0339_sensor.set_hflip = gc0339_set_hflip;
    gc0339_sensor.get_hflip = gc0339_get_hflip;
    gc0339_sensor.set_vflip = gc0339_set_vflip;
    gc0339_sensor.get_vflip = gc0339_get_vflip;
    gc0339_sensor.update_flip = gc0339_update_flip;
    gc0339_sensor.set_gain = gc0339_set_gain;
    gc0339_sensor.get_gain = gc0339_get_gain;
    gc0339_sensor.set_exposure = gc0339_set_exposure;
    gc0339_sensor.get_exposure = gc0339_get_exposure;
    gc0339_sensor.set_effect = gc0339_set_effect;
    gc0339_sensor.set_awb = gc0339_set_awb;

    strcpy(gc0339_sensor.info.name, "gc0339");
    gc0339_sensor.info.facing = CAMERA_FACING_FRONT;
    gc0339_sensor.info.orientation = 270;
    gc0339_sensor.interface_type = MIPI1;
    gc0339_sensor.mipi_lane_count = CSI_LINES_1;
    gc0339_sensor.mipi_index = CSI_INDEX_1;
    gc0339_sensor.sensor_index = CAMERA_SENSOR_SECONDARY;
    gc0339_sensor.skip_frames = GC0339_SKIP_FRAMES;
    gc0339_sensor.power_conf.pd_valid = LOW_VALID;
    gc0339_sensor.power_conf.reset_valid = LOW_VALID;
    gc0339_sensor.power_conf.vcmpd_valid = LOW_VALID;
    gc0339_sensor.i2c_config.index = I2C_PRIMARY;
    gc0339_sensor.i2c_config.speed = I2C_SPEED_400;
    gc0339_sensor.i2c_config.addr = GC0339_I2C_ADDR;
    gc0339_sensor.i2c_config.addr_bits = 8;
    gc0339_sensor.i2c_config.val_bits = I2C_8BIT;
    gc0339_sensor.preview_frmsize_index = 0;
    gc0339_sensor.capture_frmsize_index = 0;
    gc0339_sensor.frmsize_list = gc0339_framesizes;
    gc0339_sensor.fmt[STATE_PREVIEW] = V4L2_PIX_FMT_YUYV;
    gc0339_sensor.fmt[STATE_CAPTURE] = V4L2_PIX_FMT_YUYV;
    gc0339_sensor.sensor_type = SENSOR_OV;
    gc0339_sensor.isp_location = CAMERA_USE_K3ISP;
    gc0339_sensor.af_enable = 0;
    gc0339_sensor.owner = THIS_MODULE;
    gc0339_sensor.lane_clk = CLK_400M;
}

static int __init gc0339_module_init(void)
{
    gc0339_set_default();
    return register_camera_sensor(gc0339_sensor.sensor_index, &gc0339_sensor);
}

static void __exit gc0339_module_exit(void)
{
    unregister_camera_sensor(gc0339_sensor.sensor_index, &gc0339_sensor);
}

MODULE_AUTHOR("HWT101 OEM-behavior reconstruction");
MODULE_DESCRIPTION("HWT101 GC0339 K3V2 camera reconstruction");
MODULE_LICENSE("GPL");
module_init(gc0339_module_init);
module_exit(gc0339_module_exit);
'''
    src = src.replace('@@INIT@@', init_rows).replace('@@ISP@@', isp_rows)
    (outdir / 'gc0339.c').write_text(src)
    patch_makefile(root / 'drivers/media/video/hik3/capture/Makefile')

    report = Path('HWT101-GC0339-PORT.txt')
    report.write_text(
        'HWT101 GC0339 V3.29\n'
        'method: OEM-behavior reconstruction from recovered HWT101 bytes/disassembly\n'
        'not claimed as original Huawei source\n'
        'OEM init stream: 888 bytes -> 74 exact entries\n'
        'OEM ISP stream: 5872 bytes -> 734 exact struct isp_reg_t entries\n'
        'chip check: write 0xfc=0x10; ID register 0x00 must equal 0xc8\n'
        'I2C address: 0x42\n'
        'LDOs: pri-cameralog-vcc=2.85V, camera-vcc=1.8V, sec-cameralog-vcc=2.85V\n'
        'S10 base lacks OEM *_ex helpers: glue uses exported S10 k3_ispio read/write APIs with 8-bit semantics\n'
        'framesize command blob was not trustworthy; no invented register sequence is used\n'
        'status: compile/runtime candidate; device validation still required\n')
    print(report.read_text(), end='')
    print('generated:', outdir / 'gc0339.c')


if __name__ == '__main__':
    main()
