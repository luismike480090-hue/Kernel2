#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch_hwt101_v355_screen_checkpoint.py <kernel-root>')

K = Path(sys.argv[1])
p = K / 'init/main.c'
s = p.read_text()

inc_anchor = '#include <linux/idr.h>\n'
if '#include <linux/fb.h>' not in s:
    if inc_anchor not in s:
        raise SystemExit('include anchor missing')
    s = s.replace(inc_anchor, inc_anchor + '#include <linux/fb.h>\n', 1)

anchor = 'static char msgbuf[64];\n\n'
helper = r'''/* HWT101 V3.55 screen checkpoint.
 *
 * No NAND writes, no watchdog and no persistent-RAM journal are used.
 * After fb0 exists, every completed initcall leaves a 24-bit barcode in the
 * top visible band.  If the following initcall hangs, the last completed
 * function pointer remains visible.  Bits are MSB->LSB, white=1 black=0,
 * framed by two white sentinel blocks.
 */
#define HWT355_BITS 24
#define HWT355_SENTINELS 2
#define HWT355_TOTAL_BLOCKS (HWT355_BITS + HWT355_SENTINELS)
#define HWT355_BAND_ROWS 80

static void hwt355_screen_checkpoint(initcall_t fn)
{
    struct fb_info *info;
    unsigned int x, y, b, block_w, rows;
    unsigned int code;
    u8 *base;

    if (num_registered_fb < 1)
        return;
    info = registered_fb[0];
    if (!info || !info->screen_base)
        return;
    if (info->var.bits_per_pixel != 32 || info->fix.line_length < 4)
        return;
    if (info->var.xres < HWT355_TOTAL_BLOCKS || !info->var.yres)
        return;

    code = ((unsigned long)fn) & 0x00ffffffU;
    block_w = info->var.xres / HWT355_TOTAL_BLOCKS;
    if (!block_w)
        return;
    rows = info->var.yres < HWT355_BAND_ROWS ? info->var.yres : HWT355_BAND_ROWS;
    base = (u8 *)info->screen_base + info->var.yoffset * info->fix.line_length + info->var.xoffset * 4;

    for (y = 0; y < rows; y++) {
        u32 *row = (u32 *)(base + y * info->fix.line_length);
        for (b = 0; b < HWT355_TOTAL_BLOCKS; b++) {
            u32 pix;
            unsigned int start = b * block_w;
            unsigned int end = (b == HWT355_TOTAL_BLOCKS - 1) ? info->var.xres : start + block_w;

            if (b == 0 || b == HWT355_TOTAL_BLOCKS - 1)
                pix = 0x00ffffffU;
            else
                pix = (code & (1U << (HWT355_BITS - b))) ? 0x00ffffffU : 0x00000000U;

            for (x = start; x < end; x++)
                row[x] = pix;
        }
    }
    wmb();
    printk(KERN_EMERG "HWT355CHK fn=%pF addr=%p code=%06x\n", fn, fn, code);
}

'''
if 'hwt355_screen_checkpoint' not in s:
    if anchor not in s:
        raise SystemExit('msgbuf anchor missing')
    s = s.replace(anchor, anchor + helper, 1)

call_anchor = '''\tif (msgbuf[0]) {\n\t\tprintk("initcall %pF returned with %s\\n", fn, msgbuf);\n\t}\n\n\treturn ret;\n}\n'''
call_repl = '''\tif (msgbuf[0]) {\n\t\tprintk("initcall %pF returned with %s\\n", fn, msgbuf);\n\t}\n\n\thwt355_screen_checkpoint(fn);\n\treturn ret;\n}\n'''
if '\thwt355_screen_checkpoint(fn);\n\treturn ret;\n' not in s:
    if call_anchor not in s:
        raise SystemExit('do_one_initcall return anchor missing')
    s = s.replace(call_anchor, call_repl, 1)

p.write_text(s)
print('V3.55 screen checkpoint instrumentation installed')
print('BARCODE_BITS=24')
print('WHITE=1 BLACK=0')
print('SENTINELS=WHITE/WHITE')
print('NAND_WRITES=NONE')
print('WATCHDOG_PATCH=NONE')
print('PERSISTENT_RAM=NONE')