#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: add_hwt101_boot_abi.py <kernel-root>')
K=Path(sys.argv[1])
D=K/'arch/arm/mach-k3v2'
C=D/'hwt101_boot_abi.c'
C.write_text(r'''/* HWT101 boot-parity ABI providers.
 * These globals exist in Huawei OEM board/battery code and are referenced by
 * common diagnostic/touch glue even when those physical peripherals are not
 * initialized in the minimal first-boot configuration.
 */
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/notifier.h>
#include <linux/atomic.h>
#include <linux/types.h>

BLOCKING_NOTIFIER_HEAD(notifier_list_bat);
EXPORT_SYMBOL(notifier_list_bat);

atomic_t touch_is_pressed = ATOMIC_INIT(0);
EXPORT_SYMBOL(touch_is_pressed);

u32 time_finger_up = 0;
EXPORT_SYMBOL(time_finger_up);
''')
M=D/'Makefile'
s=M.read_text()
line='obj-y += hwt101_boot_abi.o\n'
if line not in s:
    s += '\n# HWT101 minimal OEM ABI providers for boot parity\n'+line
M.write_text(s)
print('HWT101 neutral boot ABI providers installed')
