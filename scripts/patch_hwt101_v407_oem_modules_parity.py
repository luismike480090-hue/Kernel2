from pathlib import Path

pth = Path("scripts/build_hwt101_v363_ntfs_prune.sh")
s = pth.read_text()

anchor = "# Build.\npushd kernel >/dev/null\n"
if anchor not in s:
    raise SystemExit("build anchor missing")

parity = r"""# V4.07 OEM module ABI parity.
# FIX10 loads compat/bluetooth/cfg80211/mac80211/wlcore/wl18xx from /system as modules.
# Keep TI shared transport and legacy WEXT provider built into the kernel.
python3 - <<'PY2'
from pathlib import Path
p = Path('kernel/net/wireless/Kconfig')
s = p.read_text()
old = 'config WIRELESS_EXT\n\tbool\n'
new = 'config WIRELESS_EXT\n\tbool\n\tdefault y\n'
if old not in s:
    raise SystemExit('WIRELESS_EXT Kconfig anchor missing')
p.write_text(s.replace(old, new, 1))
print('V407_WIRELESS_EXT_DEFAULT_Y=PASS')
PY2

pushd kernel >/dev/null
set_y(){ sed -i "/^# CONFIG_$1 is not set/d;/^CONFIG_$1=/d" .config; echo "CONFIG_$1=y" >> .config; }
set_n(){ sed -i "/^# CONFIG_$1 is not set/d;/^CONFIG_$1=/d" .config; echo "# CONFIG_$1 is not set" >> .config; }
set_v(){ sed -i "/^# CONFIG_$1 is not set/d;/^CONFIG_$1=/d" .config; echo "CONFIG_$1=$2" >> .config; }

set_n BT
set_n CFG80211
set_n MAC80211
set_y TI_ST
set_n ST_HCI
set_y WIRELESS_EXT
set_v LOCALVERSION '"-g883717a-dirty"'
set_n LOCALVERSION_AUTO

make LOCALVERSION= oldnoconfig

echo '===== V407 CONFIG AFTER OLDNOCONFIG ====='
grep -E '^(CONFIG_|# CONFIG_)(BT|CFG80211|MAC80211|TI_ST|ST_HCI|WIRELESS_EXT|WEXT_CORE|RFKILL|LOCALVERSION)' .config || true
echo '===== END V407 CONFIG ====='

grep -qx '# CONFIG_BT is not set' .config
grep -qx '# CONFIG_CFG80211 is not set' .config
! grep -Eq '^CONFIG_MAC80211=[ym]$' .config
grep -qx 'CONFIG_TI_ST=y' .config
grep -qx 'CONFIG_WIRELESS_EXT=y' .config
grep -qx 'CONFIG_WEXT_CORE=y' .config
grep -qx 'CONFIG_LOCALVERSION="-g883717a-dirty"' .config
grep -qx '# CONFIG_LOCALVERSION_AUTO is not set' .config

: > .scmversion
KR="$(make -s LOCALVERSION= kernelrelease)"
echo "V407_KERNELRELEASE=$KR"
test "$KR" = '3.0.8-g883717a-dirty'
popd >/dev/null

"""

s = s.replace(anchor, parity + anchor, 1)

if "make -j2 zImage" not in s:
    raise SystemExit("zImage build command missing")
s = s.replace("make -j2 zImage", "make LOCALVERSION= -j2 zImage", 1)

pth.write_text(s)
print("V407_DERIVATION=PASS")
print("BASE=V4.06_YAFFS64")
print("CHANGE=OEM_MODULE_ABI_PARITY_PLUS_EXACT_UTS_RELEASE")
