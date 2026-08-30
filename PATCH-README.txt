HWT101 V3 -> V3.1 PATCH

Solo contiene los 3 archivos modificados.

Subir/reemplazar:
1. .github/workflows/BUILD-HWT101-HYBRID-V3.1.yml   (nuevo workflow)
2. scripts/apply_hwt101_v3.sh                       (reemplazar)
3. scripts/verify_v3.py                             (reemplazar)

Corrección principal:
- CONFIG_LOCALVERSION="-g883717a-dirty"
- CONFIG_LOCALVERSION_AUTO desactivado
- make se ejecuta con LOCALVERSION= para impedir el '+' automático de Linux 3.0.x
- oldnoconfig reemplaza "yes | oldconfig"

Resultado exigido:
3.0.8-g883717a-dirty
