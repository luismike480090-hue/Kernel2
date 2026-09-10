#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch_hwt101_v370_raw_oob_diag.py <kernel-root>')

K = Path(sys.argv[1])
hp = K / 'drivers/mtd/nand/hinand_hwt101.c'
h = hp.read_text()

anchor = 'static inline u32 nfc_read(struct hwt_hinand *h, unsigned int reg)'
if anchor not in h:
    raise SystemExit('anchor missing')

block = r'''
static void hwt_readstart(struct hwt_hinand *h);

#define HWT_RAW_HITS 3
#define HWT_SYSTEM_START_PAGE 91392U
#define HWT_RAW_SCAN_PAGES 512U

struct hwt_raw_sample {
    u32 page;
    u8 data16[16];
    u8 oob448[448];
};
static struct hwt_raw_sample hwt_raw[HWT_RAW_HITS];
static int hwt_raw_hits;

static int hwt_raw_nonff(const u8 *p, int n)
{
    int i;
    for (i = 0; i < n; i++)
        if (p[i] != 0xff)
            return 1;
    return 0;
}

static void hwt_raw_read_page(struct hwt_hinand *h, u32 page)
{
    memset(h->dma_buf, 0xff, HWT_DMA_SIZE);
    h->addr[0] = (page & 0xffffU) << 16;
    h->addr[1] = (page >> 16) & 0xffU;
    h->addr_cycle = 5;
    h->column = 0;
    h->page_offset = 0;
    hwt_readstart(h);
}

static void hwt_capture_system_raw(struct hwt_hinand *h)
{
    u32 i, p;
    hwt_raw_hits = 0;
    for (i = 0; i < HWT_RAW_SCAN_PAGES && hwt_raw_hits < HWT_RAW_HITS; i++) {
        p = HWT_SYSTEM_START_PAGE + i;
        hwt_raw_read_page(h, p);
        if (!hwt_raw_nonff(h->dma_buf + 8192, 448))
            continue;
        hwt_raw[hwt_raw_hits].page = p;
        memcpy(hwt_raw[hwt_raw_hits].data16, h->dma_buf, 16);
        memcpy(hwt_raw[hwt_raw_hits].oob448, h->dma_buf + 8192, 448);
        hwt_raw_hits++;
    }
}

static int hwt_raw_oob_read(char *page, char **start, off_t off,
                            int count, int *eof, void *data)
{
    int len = 0, i, j;
    len += scnprintf(page + len, count - len,
                     "HWT101_V370_RAW_OOB\nSYSTEM_START_PAGE=%u\nSCAN_PAGES=%u\nHITS=%d\n",
                     HWT_SYSTEM_START_PAGE, HWT_RAW_SCAN_PAGES, hwt_raw_hits);
    for (i = 0; i < hwt_raw_hits && len < count - 64; i++) {
        len += scnprintf(page + len, count - len, "HIT%d_PAGE=%u\nDATA16=", i, hwt_raw[i].page);
        for (j = 0; j < 16 && len < count - 4; j++)
            len += scnprintf(page + len, count - len, "%02x", hwt_raw[i].data16[j]);
        len += scnprintf(page + len, count - len, "\nOOB448=");
        for (j = 0; j < 448 && len < count - 4; j++)
            len += scnprintf(page + len, count - len, "%02x", hwt_raw[i].oob448[j]);
        len += scnprintf(page + len, count - len, "\n");
    }
    *eof = 1;
    return len;
}

'''
h = h.replace(anchor, block + anchor, 1)

old = 'if(ret){hwt_diag_stage=-60;ret=-ENXIO;goto err_irq;}hwt_diag_stage=60;'
new = 'if(ret){hwt_diag_stage=-60;ret=-ENXIO;goto err_irq;}hwt_diag_stage=60;hwt_capture_system_raw(h);'
if old not in h:
    raise SystemExit('scan anchor missing')
h = h.replace(old, new, 1)

old2 = 'static int __init hinand_module_init(void){int ret;create_proc_read_entry("hwt_hinand_diag",0444,NULL,hwt_hinand_diag_read,NULL);'
new2 = 'static int __init hinand_module_init(void){int ret;create_proc_read_entry("hwt_hinand_diag",0444,NULL,hwt_hinand_diag_read,NULL);create_proc_read_entry("hwt_nand_raw_oob",0444,NULL,hwt_raw_oob_read,NULL);'
if old2 not in h:
    raise SystemExit('proc anchor missing')
h = h.replace(old2, new2, 1)

h = h.replace('HWT101_V369_HINAND_DIAG', 'HWT101_V370_HINAND_DIAG')
hp.write_text(h)

for needle in (
    'HWT101_V370_HINAND_DIAG',
    'HWT101_V370_RAW_OOB',
    'HWT_SYSTEM_START_PAGE 91392U',
    'hwt_capture_system_raw(h);',
    'hwt_nand_raw_oob',
):
    if needle not in hp.read_text():
        raise SystemExit('V3.70 gate failed: ' + needle)

print('V370_RAW_OOB_DIAG=PASS')
print('WRITE_OPERATIONS=NONE')
print('SYSTEM_START_PAGE=91392')
print('SCAN_PAGES=512')
print('RAW_HITS=3')
