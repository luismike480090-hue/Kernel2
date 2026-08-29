# HWT101 HYBRID KERNEL SOURCE V1

Este paquete es la primera reconstrucción de fuente híbrida preparada para COMPILAR.
No se presenta como un kernel ya probado en la tablet.

## Qué está reconstruido con evidencia OEM directa

### SN65DSI83
Se recuperó del FIX10:
- nombre del driver: sn65dsi83
- dirección I2C de la plataforma: 0x2d
- GPIO EN: 79 (confirmado por dmesg)
- regulador: lcd-vcc
- tensión: 2,600,000 uV
- early-suspend/resume
- nivel early_suspend: 149
- tabla exacta de 43 pares registro/valor, byte por byte.

La tabla tiene SHA256:
61d06a9a8431195a7c6baf779c3040663e3ff99d8c1389fb187d27781ec8ef61

### Cámara
Se guardaron sin alterar los blobs OEM:
- isp_init_regs_gc0339: 5872 bytes
- gc0339_init_regs: 888 bytes
- gc0339_framesize_full: 20 bytes
- s5k5cag_sunny_init_regs: 36684 bytes
- isp_init_regs_s5k5cag: 16 bytes

No se reinterpretan todavía como estructuras C porque hacerlo sin confirmar el layout Hik3 sería inventar datos.

## Base de compilación
https://github.com/xxx-man/android_kernel_huawei_s10-101x
commit observado en nuestro build previo:
d0ea9345cfc3992a3d959482579a8fc7f1108802

Referencia Huawei K3V2 adicional:
https://github.com/mangusta86/android_kernel_huawei_k3v2oem1

## Memoria
El workflow activa únicamente:
CONFIG_SWAP=y
CONFIG_STAGING=y
CONFIG_ZRAM=y
CONFIG_XVMALLOC=y
CONFIG_LZO_COMPRESS=y
CONFIG_LZO_DECOMPRESS=y
# CONFIG_ZRAM_DEBUG is not set

## Cómo obtener el zImage
Sube todo este ZIP descomprimido a un repositorio GitHub y ejecuta:
Actions -> HWT101 Hybrid Kernel V1 -> Run workflow

El artifact resultante se llama:
HWT101-HYBRID-KERNEL-V1

## BOOT
Cuando el zImage compile, scripts/pack_boot_fix10.py vuelve a usar el ramdisk y header de FIX10.
NO hace wipe y NO modifica system/userdata.

## Estado de seguridad
SN65DSI83 tiene reconstrucción de alta confianza basada en el binario OEM.
BQ2419X y S5K5CAG se apoyan en árboles Huawei K3V2.
FT5X0X y GC0339 aún requieren terminar la reconstrucción tipada antes de considerar este kernel final.
El touch activo observado en el dump fue Goodix, por lo que FT5X0X no debe reemplazar Goodix.
