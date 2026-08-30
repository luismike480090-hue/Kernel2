HWT101 HYBRID KERNEL V3
=======================

Purpose
-------
Continue from the successful V2 build without flashing an incomplete kernel.
V3 makes two concrete corrections immediately:
1) Forces exact OEM kernelrelease: 3.0.8-g883717a-dirty (no trailing '+').
2) Imports and enables Huawei's K3V2-era bq2419x_charger.c from the cm-11 reference tree.

It also inventories Goodix / FT5X0X / GC0339 / S5K5CAG donor sources and records board I2C tables, so the next artifact tells us exactly what remains rather than guessing.

Important
---------
DO NOT FLASH merely because GitHub Actions turns green.
Open FLASHABILITY.txt in the artifact.
Only FLASHABLE=YES means the automated parity gate found:
- SWAP/ZRAM/XVMALLOC/LZO
- HWT101 SN65 driver
- exact kernelrelease
- BQ2419X
- active Goodix touch
- GC0339
- S5K5CAG

FT5X0X is treated as secondary because the working OEM boot log shows it fails at I2C 0x38 while Goodix later becomes the active input device.

No wipe commands are included. This package does not touch system/userdata.

Why V2 was not final
--------------------
V2 zImage compiled, but its embedded release was 3.0.8-g883717a-dirty+ and its System.map did not contain Goodix, FT5X0X, GC0339, S5K5CAG or BQ2419X symbols.

Next action
-----------
Upload this package to the GitHub repository root and run:
Actions -> HWT101 Hybrid Kernel V3 -> Run workflow
Then download HWT101-HYBRID-KERNEL-V3 and send that ZIP back for analysis.
