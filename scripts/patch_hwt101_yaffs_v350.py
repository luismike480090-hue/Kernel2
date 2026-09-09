#!/usr/bin/env python3
from pathlib import Path
import re, sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch_hwt101_yaffs_v350.py <kernel-root>')
K = Path(sys.argv[1])
y = K / 'fs/yaffs2/yaffs_vfs.c'
ys = y.read_text()

# cm-10.1 carries old pre-3.0 BKL/get_sb glue. Port only the VFS registration API;
# YAFFS on-flash/data logic is left unchanged.
ys = re.sub(r'^\s*#include\s*<linux/smp_lock\.h>\s*\n', '', ys, flags=re.M)
if re.search(r'\b(lock_kernel|unlock_kernel)\b', ys):
    raise SystemExit('YAFFS still uses Big Kernel Lock calls')

ys = re.sub(
    r'static int yaffs_read_super\(struct file_system_type \*fs,\s*int flags, const char \*dev_name,\s*void \*data, struct vfsmount \*mnt\)\s*\{\s*return get_sb_bdev\(fs, flags, dev_name, data,\s*yaffs_internal_read_super_mtd, mnt\);\s*\}',
    'static struct dentry *yaffs_mount(struct file_system_type *fs,\n\t\t\t\t int flags, const char *dev_name, void *data)\n{\n\treturn mount_bdev(fs, flags, dev_name, data,\n\t\t\t  yaffs_internal_read_super_mtd);\n}',
    ys, flags=re.S)
ys = re.sub(
    r'static int yaffs2_read_super\(struct file_system_type \*fs,\s*int flags, const char \*dev_name, void \*data,\s*struct vfsmount \*mnt\)\s*\{\s*return get_sb_bdev\(fs, flags, dev_name, data,\s*yaffs2_internal_read_super_mtd, mnt\);\s*\}',
    'static struct dentry *yaffs2_mount(struct file_system_type *fs,\n\t\t\t\t  int flags, const char *dev_name, void *data)\n{\n\treturn mount_bdev(fs, flags, dev_name, data,\n\t\t\t  yaffs2_internal_read_super_mtd);\n}',
    ys, flags=re.S)
ys = ys.replace('.get_sb = yaffs_read_super,', '.mount = yaffs_mount,')
ys = ys.replace('.get_sb = yaffs2_read_super,', '.mount = yaffs2_mount,')
y.write_text(ys)

check = y.read_text()
if 'linux/smp_lock.h' in check or 'get_sb_bdev' in check or '.get_sb =' in check:
    raise SystemExit('YAFFS legacy VFS API survived compatibility patch')
if 'mount_bdev(fs, flags, dev_name, data' not in check:
    raise SystemExit('YAFFS mount_bdev compatibility patch missing')
print('V3.50 YAFFS VFS compatibility: PASS')
