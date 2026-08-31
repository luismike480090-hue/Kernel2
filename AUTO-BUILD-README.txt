Kernel2 AUTO build

Incluye V3.13 y un workflow mejorado.
El workflow sigue clonando automáticamente:
- xxx-man/android_kernel_huawei_s10-101x @ d0ea9345...
- mangusta86/android_kernel_huawei_k3v2oem1 branch cm-11

En fallo captura automáticamente:
- errores completos
- LINK-PROVIDER-IMPORT.txt
- .config
- bq27510_battery.c de S10 y donor
- todas las apariciones con contexto de
  ipps_update_power_capacity
  get_boot_into_recovery_flag

No modifica system/userdata ni realiza wipe.
