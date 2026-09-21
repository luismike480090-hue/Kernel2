#!/usr/bin/env python3
from pathlib import Path
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else "kernel")

# 1) Keep V4.05 physical NAND guard but silence only the ALLOW printk spam.
nand = root / "drivers/mtd/nand/hinand_hwt101.c"
s = nand.read_text()
old1='''    printk(KERN_DEBUG "HWT101_V405_ANDROID_GUARD: ALLOW PAGEPROG page=0x%x\\n", page);\n'''
old2='''        printk(KERN_DEBUG "HWT101_V405_ANDROID_GUARD: ALLOW ERASE2 page=0x%x\\n", page);\n'''
if old1 not in s:
    raise SystemExit("ALLOW PAGEPROG printk anchor missing")
if old2 not in s:
    raise SystemExit("ALLOW ERASE2 printk anchor missing")
s = s.replace(old1, "", 1).replace(old2, "", 1)
nand.write_text(s)

# 2) HDMI: if the board did not provide the HDMI regulators/clocks/iomux,
# never dereference NULL from HDMIDaemon. Internal LCD remains independent.
hdmi = root / "drivers/video/k3/hdmi/k3_hdmi_hw.c"
s = hdmi.read_text()

on_anchor='''void hw_core_power_on(void)\n{\n    IN_FUNCTION;\n\n#if HDMI_CHIP_VER\n\n    if (!hdmi.in_reset) {\n'''
on_new='''void hw_core_power_on(void)\n{\n    IN_FUNCTION;\n\n#if HDMI_CHIP_VER\n\n    if (!hw_res.edc_vcc || !hw_res.clk_hdmi || !hw_res.clk_pclk_hdmi ||\n        !hw_res.clk_edc1 || !hw_res.clk_ldi1 || !hw_res.iomux_block ||\n        !hw_res.iomux_block_config || (!hw_support_mhl() && !hw_res.charge_pump)) {\n        loge("HDMI resources incomplete; skip power-on safely.\\n");\n        OUT_FUNCTION;\n        return;\n    }\n\n    if (!hdmi.in_reset) {\n'''
if on_anchor not in s:
    raise SystemExit("hw_core_power_on anchor missing")
s = s.replace(on_anchor, on_new, 1)

off_anchor='''void  hw_core_power_off(void)\n{\n#if HDMI_CHIP_VER\n    int ret = 0;\n#endif  \n\n    IN_FUNCTION;\n\n#if HDMI_CHIP_VER\n\n    /* Turn off DDC */\n'''
off_new='''void  hw_core_power_off(void)\n{\n#if HDMI_CHIP_VER\n    int ret = 0;\n#endif  \n\n    IN_FUNCTION;\n\n#if HDMI_CHIP_VER\n\n    if (!hw_res.edc_vcc || !hw_res.clk_hdmi || !hw_res.clk_pclk_hdmi ||\n        !hw_res.clk_edc1 || !hw_res.clk_ldi1 || !hw_res.iomux_block ||\n        !hw_res.iomux_block_config || (!hw_support_mhl() && !hw_res.charge_pump)) {\n        loge("HDMI resources incomplete; skip power-off safely.\\n");\n        OUT_FUNCTION;\n        return;\n    }\n\n    /* Turn off DDC */\n'''
if off_anchor not in s:
    raise SystemExit("hw_core_power_off anchor missing")
s = s.replace(off_anchor, off_new, 1)
hdmi.write_text(s)

ns=nand.read_text()
hs=hdmi.read_text()
assert "HWT101_V405_ANDROID_GUARD: BLOCK PAGEPROG" in ns
assert "HWT101_V405_ANDROID_GUARD: BLOCK ERASE2" in ns
assert "HWT101_V405_ANDROID_GUARD: ALLOW PAGEPROG" not in ns
assert "HWT101_V405_ANDROID_GUARD: ALLOW ERASE2" not in ns
assert "#define HWT_ANDROID_FIRST_PAGE 0x16500U" in ns
assert "#define HWT_ANDROID_LAST_PAGE  0xfffffU" in ns
assert "HDMI resources incomplete; skip power-on safely." in hs
assert "HDMI resources incomplete; skip power-off safely." in hs

print("V409_PATCH=PASS")
print("BASE=V407B_HARDWARE_PASS")
print("HDMI_NULL_GUARD=YES")
print("NAND_ALLOW_PRINTK=REMOVED")
print("NAND_BLOCK_GUARD=PRESERVED")
print("YAFFS64=UNCHANGED")
