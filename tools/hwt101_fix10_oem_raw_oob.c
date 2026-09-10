/* HWT101 FIX10 OEM RAW/OOB extractor
 * Freestanding ARM EABI, no libc. Read-only.
 */
typedef unsigned int u32;
typedef unsigned char u8;

struct mtd_oob_buf {
    u32 start;
    u32 length;
    u8 *ptr;
};

#define O_RDONLY 0
#define MEMREADOOB 0xC00C4D04u

static inline long sc1(long n, long a)
{
    register long r0 asm("r0") = a;
    register long r7 asm("r7") = n;
    asm volatile("svc 0" : "+r"(r0) : "r"(r7) : "memory");
    return r0;
}
static inline long sc2(long n, long a, long b)
{
    register long r0 asm("r0") = a;
    register long r1 asm("r1") = b;
    register long r7 asm("r7") = n;
    asm volatile("svc 0" : "+r"(r0) : "r"(r1), "r"(r7) : "memory");
    return r0;
}
static inline long sc3(long n, long a, long b, long c)
{
    register long r0 asm("r0") = a;
    register long r1 asm("r1") = b;
    register long r2 asm("r2") = c;
    register long r7 asm("r7") = n;
    asm volatile("svc 0" : "+r"(r0) : "r"(r1), "r"(r2), "r"(r7) : "memory");
    return r0;
}

static long sys_open(const char *p, int f, int m) { return sc3(5,(long)p,f,m); }
static long sys_close(int fd) { return sc1(6,fd); }
static long sys_read(int fd, void *p, u32 n) { return sc3(3,fd,(long)p,n); }
static long sys_write(int fd, const void *p, u32 n) { return sc3(4,fd,(long)p,n); }
static long sys_lseek(int fd, u32 off, int whence) { return sc3(19,fd,off,whence); }
static long sys_ioctl(int fd, u32 req, void *arg) { return sc3(54,fd,req,(long)arg); }
static void sys_exit(int code) { sc1(1,code); for(;;){} }

static u32 slen(const char *s) { u32 n=0; while(s[n]) n++; return n; }
static void puts2(const char *s) { sys_write(1,s,slen(s)); }
static char hx(unsigned x) { return "0123456789abcdef"[x&15]; }

static void hexbuf(const u8 *p, u32 n)
{
    char b[128];
    u32 i,j=0;
    for(i=0;i<n;i++){
        b[j++]=hx(p[i]>>4); b[j++]=hx(p[i]);
        if(j>=sizeof(b)-2){ sys_write(1,b,j); j=0; }
    }
    if(j) sys_write(1,b,j);
}

static void decu(u32 v)
{
    static const u32 p10[] = {1000000000u,100000000u,10000000u,1000000u,100000u,10000u,1000u,100u,10u,1u};
    int i,started=0;
    char ch;
    for(i=0;i<10;i++){
        unsigned d=0;
        while(v>=p10[i]){ v-=p10[i]; d++; }
        if(d || started || i==9){
            ch=(char)('0'+d);
            sys_write(1,&ch,1);
            started=1;
        }
    }
}

static int open_mtd0(void)
{
    static const char *paths[]={"/dev/mtd/mtd0","/dev/mtd0","/dev/block/mtd0",0};
    int i; long fd;
    for(i=0;paths[i];i++){
        fd=sys_open(paths[i],O_RDONLY,0);
        if(fd>=0) return (int)fd;
    }
    return -1;
}

void _start(void)
{
    static u8 data[8192];
    static u8 oob[448];
    int fd = open_mtd0();
    u32 page;

    puts2("HWT101_FIX10_OEM_RAW_OOB_V1\n");
    puts2("DEVICE=system_mtd0\n");
    puts2("PAGE_SIZE=8192\nOOB_SIZE=448\nPAGES=0,1,2\n");

    if(fd<0){
        puts2("ERROR=open_mtd0_failed\n");
        sys_exit(2);
    }

    for(page=0;page<3;page++){
        long r;
        struct mtd_oob_buf ob;
        u32 off=page*8192u;
        u32 i;
        for(i=0;i<8192;i++) data[i]=0;
        for(i=0;i<448;i++) oob[i]=0;

        r=sys_lseek(fd,off,0);
        puts2("PAGE="); decu(page); puts2("\n");
        if(r<0){ puts2("LSEEK_ERR\n"); continue; }

        r=sys_read(fd,data,8192);
        puts2("DATA_READ="); decu((u32)(r<0?0:r)); puts2("\n");
        puts2("DATA16="); hexbuf(data,16); puts2("\n");

        ob.start=off;
        ob.length=448;
        ob.ptr=oob;
        r=sys_ioctl(fd,MEMREADOOB,&ob);
        puts2("OOB_IOCTL_RET=");
        if(r<0) puts2("NEG"); else decu((u32)r);
        puts2("\nOOB448=");
        hexbuf(oob,448);
        puts2("\n");
    }

    sys_close(fd);
    sys_exit(0);
}

/* rebuild trigger after libgcc link fix */
