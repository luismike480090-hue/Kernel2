#!/usr/bin/env python3
from pathlib import Path
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else 'kernel')

mtdif = root / 'fs/yaffs2/yaffs_mtdif.c'
mtdif2 = root / 'fs/yaffs2/yaffs_mtdif2.c'

s = mtdif.read_text()
old = '''\tu32 addr =\n\t    ((loff_t) block_no) * dev->param.total_bytes_per_chunk\n\t    * dev->param.chunks_per_block;'''
new = '''\tloff_t addr =\n\t    ((loff_t) block_no) * dev->param.total_bytes_per_chunk\n\t    * dev->param.chunks_per_block;'''
if old not in s:
    raise SystemExit('yaffs_mtdif.c erase address anchor missing')
s = s.replace(old, new, 1)
mtdif.write_text(s)

s = mtdif2.read_text()
old_mark = '''\tretval =\n\t    mtd->block_markbad(mtd,\n\t\t\t       block_no * dev->param.chunks_per_block *\n\t\t\t       dev->param.total_bytes_per_chunk);'''
new_mark = '''\tretval =\n\t    mtd->block_markbad(mtd,\n\t\t\t       ((loff_t) block_no) * dev->param.chunks_per_block *\n\t\t\t       dev->param.total_bytes_per_chunk);'''
if old_mark not in s:
    raise SystemExit('yaffs_mtdif2.c mark_block_bad anchor missing')
s = s.replace(old_mark, new_mark, 1)

old_query = '''\tretval =\n\t    mtd->block_isbad(mtd,\n\t\t\t     block_no * dev->param.chunks_per_block *\n\t\t\t     dev->param.total_bytes_per_chunk);'''
new_query = '''\tretval =\n\t    mtd->block_isbad(mtd,\n\t\t\t     ((loff_t) block_no) * dev->param.chunks_per_block *\n\t\t\t     dev->param.total_bytes_per_chunk);'''
if old_query not in s:
    raise SystemExit('yaffs_mtdif2.c query_block anchor missing')
s = s.replace(old_query, new_query, 1)
mtdif2.write_text(s)

# Hard assertions: these are the three 4GiB-sensitive byte-address calculations.
assert 'loff_t addr =' in mtdif.read_text()
assert '((loff_t) block_no) * dev->param.chunks_per_block *' in mtdif2.read_text()
assert mtdif2.read_text().count('((loff_t) block_no) * dev->param.chunks_per_block *') >= 2

print('V406_YAFFS64_USERDATA=PASS')
print('FIX_ERASE_ADDR=loff_t')
print('FIX_MARKBAD_ADDR=loff_t')
print('FIX_QUERY_BLOCK_ADDR=loff_t')
print('REASON=prevent_32bit_wrap_at_4GiB')
