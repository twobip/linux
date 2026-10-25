# SPDX-License-Identifier: GPL-2.0-only OR MIT
# Copyright 2026 Ryan Murray
"""Desktop modeset callbacks through the production dispatcher and DMA policy."""
from common import block
import lifecycle


def modeset_unmap(root):
    base = root / 'drivers/gpu/drm/apple'
    iomfb = (base / 'iomfb.c').read_text()
    template = (base / 'iomfb_template.c').read_text()
    desktop = (base / 'iomfb_v26_6_desktop.c').read_text()
    header = (base / 'iomfb_v26_6_desktop.h').read_text()
    # Reuse the transport boundary mocks, retaining the real callback dispatcher.
    prefix = lifecycle.dispatcher(root).split('static bool dcp_external_zero_reply(')[0]
    prefix = prefix.replace('struct dcp_channel { unsigned depth; void *output[8]; unsigned end[8]; };', r'''
struct apple_dcp;
typedef void (*dcp_callback_t)(struct apple_dcp *, void *, void *);
struct dcp_channel {
    unsigned depth; void *output[8], *cookies[8]; unsigned end[8];
    dcp_callback_t callbacks[8]; struct dcp_packet_header header[8];
};
struct sg_table {void *sgl;};
struct dcp_mem_descriptor {void *buf;u64 dva;size_t size;bool piodma_mapped;struct sg_table map;};
''')
    prefix = prefix.replace('    struct dcp_channel channel;', r'''
    struct dcp_channel channel, command;
    struct dcp_mem_descriptor memdesc[4];
    unsigned long memdesc_map[1];void *iommu_dom;
''')
    prefix = prefix.replace('DCP_CONTEXT_CB = 0, DCP_CONTEXT_ASYNC = 3',
                            'DCP_CONTEXT_CB = 0, DCP_CONTEXT_CMD = 1, DCP_CONTEXT_ASYNC = 3')
    prefix = prefix.replace('(void)c; return &d->channel;',
                            'return c==DCP_CONTEXT_CMD?&d->command:&d->channel;')
    prefix = prefix.replace('((void)dev)', '((void)dcp->dev)')
    prefix += r'''
#include <sys/types.h>
#define DCP_FW_NAME(n) n
#define DCP_FW_H17(v) 0
#define DCP_FW_DESKTOP_26(v) 1
#define SZ_16K 16384U
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define WRITE_ONCE(p,v) ((p)=(v))
#undef static_assert
#define static_assert(c) _Static_assert(c,#c)
#define trace_iomfb_callback(...) ((void)0)
#define dev_warn_dma(...) ((void)0)
struct dcp_map_buf_req {u64 buffer;};
struct dcp_map_buf_resp {u64 buffer,dva;};
struct dcp_unmap_buf_resp {u64 buffer,vaddr,dva;u8 unk,buf_null;};
struct dcp_wait_cookie {unsigned status;bool replied;int done,refcount;};
static bool test_bit(unsigned b,unsigned long *p) {return !!(*p & (1UL<<b));}
static u64 get_unaligned_le64(const void *p) {u64 v;memcpy(&v,p,8);return v;}
static u8 dcp_pop_depth(unsigned *p) {assert(*p);return --(*p);}
static void release_wait_cookie(int *p) {assert(false);}
static void kref_put(int *p,void (*release)(int *)) {assert(*p==2);--*p;(void)release;}
#define IOMMU_READ 1
#define IOMMU_WRITE 2
static unsigned maps,unmaps;
static ssize_t iommu_map_sgtable(void *domain,u64 dva,struct sg_table *map,int flags)
{assert(domain && dva==0x8000 && map->sgl && flags==3);maps++;return SZ_16K;}
static size_t iommu_unmap(void *domain,u64 dva,size_t size)
{assert(domain && dva==0x8000 && size==SZ_16K);unmaps++;return size;}
'''
    # dev logging in the DMA helper has no local 'dev', unlike the dispatcher.
    unmap = block(template, 'static bool dcpep_unmap_piodma(')
    unmap = unmap.replace('dev_warn(', 'dev_warn_dma(').replace('dev_err(', 'dev_warn_dma(')
    handlers = block(desktop, 'static const iomfb_cb_handler cb_handlers[')
    binding = next(line for line in handlers.splitlines() if '[202]' in line)
    mapping = block(template, 'static bool dcpep_map_piodma(').replace('dev_err(', 'dev_warn_dma(')
    production = (mapping + '\n' + unmap + '\n' + block(desktop, 'static bool trampoline_unmap_piodma_v26_6(') +
                  '\n' + block(iomfb, 'static bool dcp_external_zero_reply(') +
                  '\n' + block(iomfb, 'static void dcpep_handle_cb(').replace('struct device *dev =', 'struct device *dev __attribute__((unused)) =') +
                  '\n' + block(iomfb, 'static void dcpep_handle_ack(') +
                  '\n' + block(template, 'static void complete_set_digital_out_mode('))
    return prefix + production + '\n' + r'''
int main(void)
{
    struct device_node node={0};struct device dev={&node};
    bool (*handlers[IOMFB_MAX_CB])(struct apple_dcp *,int,void *,void *)={
''' + binding + r'''
    };
    struct apple_dcp d={.dev=&dev,.fw_compat=DCP_FIRMWARE_V_26_6_DESKTOP,
        .cb_handlers=handlers,.memdesc_map={2},.iommu_dom=&d};
    union {u64 align;u8 data[sizeof(struct dcp_packet_header)+24];} packet;
    struct dcp_packet_header *h=(void *)packet.data;
    struct {struct dcp_packet_header h;u32 input[2];u32 status;} command={
        .h={.in_len=8,.out_len=4},.status=0};
    struct dcp_wait_cookie wait={.status=~0U,.refcount=2};
    /* The firmware pauses an A413 modeset until its D202 is acknowledged. */
    d.command.depth=1;d.command.header[0]=command.h;
    d.command.callbacks[0]=complete_set_digital_out_mode;
    d.command.cookies[0]=&wait;d.command.output[0]=&command.status;
    d.memdesc[1]=(struct dcp_mem_descriptor){.buf=&d,.dva=0x8000,.size=4096,.map={.sgl=&d}};
    struct dcp_map_buf_req map_request={.buffer=1};struct dcp_map_buf_resp map_reply;
    assert(dcpep_map_piodma(&d,&map_request,&map_reply));
    assert(maps==1 && d.memdesc[1].piodma_mapped && map_reply.buffer==1 && map_reply.dva==0x8000);
    assert(!dcpep_map_piodma(&d,&map_request,&map_reply) && maps==1);
    memset(&packet,0,sizeof(packet));h->in_len=24;
    u64 fields[]={1,0x1234,0x8000};memcpy(packet.data+sizeof(*h),fields,24);
    case_tag=202;acks=0;
    dcpep_handle_cb(&d,DCP_CONTEXT_CB,h,sizeof(*h)+24,0);
    assert(acks==1 && !d.crashed && !d.channel.depth && unmaps==1);
    assert(!d.memdesc[1].piodma_mapped && d.command.depth==1 && !wait.done);
    /* No firmware response can arrive until the empty callback ACK above. */
    dcpep_handle_ack(&d,DCP_CONTEXT_CMD);
    assert(wait.done && wait.replied && !wait.status && wait.refcount==1 && !d.command.depth);
    /* A repeated release cannot unmap the same address a second time. */
    dcpep_handle_cb(&d,DCP_CONTEXT_CB,h,sizeof(*h)+24,0);
    assert(acks==2 && unmaps==1 && !d.crashed);
    /* A later modeset can map the same descriptor again after release. */
    assert(dcpep_map_piodma(&d,&map_request,&map_reply) && maps==2);
    fields[2]=0x9000;memcpy(packet.data+sizeof(*h),fields,24);
    dcpep_handle_cb(&d,DCP_CONTEXT_CB,h,sizeof(*h)+24,0);
    assert(acks==3 && unmaps==1 && d.memdesc[1].piodma_mapped);
    fields[0]=4;fields[2]=0x8000;memcpy(packet.data+sizeof(*h),fields,24);
    dcpep_handle_cb(&d,DCP_CONTEXT_CB,h,sizeof(*h)+24,0);
    assert(acks==4 && unmaps==1 && d.memdesc[1].piodma_mapped);
    /* The declared desktop shape is exact, with no guessed reply bytes. */
    assert(!iomfb_check_callback_v26_6_desktop(202,26,0));
    assert(!iomfb_check_callback_v26_6_desktop(202,24,4));
    h->in_len=23;
    dcpep_handle_cb(&d,DCP_CONTEXT_CB,h,sizeof(*h)+24,0);
    assert(d.crashed && acks==4 && unmaps==1);
    return 0;
}
'''
