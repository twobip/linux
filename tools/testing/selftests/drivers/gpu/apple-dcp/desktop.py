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
struct dcp_mem_descriptor {void *buf;u64 dva,reg;size_t size;bool piodma_mapped;struct sg_table map;};
''')
    prefix = prefix.replace('    struct dcp_channel channel;', r'''
    struct dcp_channel channel, command;
    struct dcp_mem_descriptor memdesc[4];
    unsigned long memdesc_map[1];void *iommu_dom;
    struct resource {u64 start,end;} *disp_registers[1];int nr_disp_registers;
''')
    prefix = prefix.replace('DCP_CONTEXT_CB = 0, DCP_CONTEXT_ASYNC = 3',
                            'DCP_CONTEXT_CB = 0, DCP_CONTEXT_CMD = 1, DCP_CONTEXT_ASYNC = 3')
    prefix = prefix.replace('(void)c; return &d->channel;',
                            'return c==DCP_CONTEXT_CMD?&d->command:&d->channel;')
    prefix = prefix.replace('((void)dev)', '((void)dcp->dev)')
    prefix += r'''
#include <sys/types.h>
typedef u64 __le64;typedef u32 __le32;
#define __packed __attribute__((packed))
typedef u64 dma_addr_t;
#define DCP_FW_NAME(n) n
#define DCP_FW_H17(v) 0
#define DCP_FW_DESKTOP_26(v) 1
#define SZ_16K 16384U
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define DCP_MAX_MAPPINGS 4
#undef static_assert
#define static_assert(c) _Static_assert(c,#c)
#define trace_iomfb_callback(...) ((void)0)
#define dev_warn_dma(...) ((void)0)
struct dcp_map_physical_req {u64 paddr,size;u32 flags;u8 dva_null,dva_size_null,padding[2];} __attribute__((packed));
struct dcp_map_physical_resp {u64 dva,dva_size;u32 mem_desc_id;} __attribute__((packed));
struct dcp_map_buf_req {u64 buffer;};
struct dcp_map_buf_resp {u64 buffer,dva;};
struct dcp_unmap_buf_resp {u64 buffer,vaddr,dva;u8 unk,buf_null;};
struct dcp_wait_cookie {unsigned status;bool replied;int done,refcount;};
#define dev_warn_release(...) ((void)0)
#define dev_err_release(...) ((void)0)
#define DMA_BIDIRECTIONAL 0
#define round_down(x,y) ((x) & ~((__typeof__(x))(y)-1))
#define check_add_overflow(a,b,p) __builtin_add_overflow(a,b,p)
static unsigned physical_maps;
static unsigned find_first_zero_bit(unsigned long *map,unsigned count)
{for(unsigned i=0;i<count;i++)if(!(*map & (1UL<<i)))return i;return count;}
static void set_bit(unsigned b,unsigned long *p) {*p |= 1UL<<b;}
static u64 dma_map_resource(struct device *dev,u64 pa,u64 size,int dir,int flags)
{assert(dev && pa==0x123400 && size==4096 && !dir && !flags);physical_maps++;return 0x8000;}
static bool dma_mapping_error(struct device *dev,u64 dva) {assert(dev && dva==0x8000);return false;}
static unsigned frees,resource_unmaps;
static void sg_free_table(struct sg_table *map) {assert(map->sgl);}
static void dma_free_coherent(struct device *dev,size_t size,void *buf,u64 dva)
{assert(dev && size==SZ_16K && buf && dva==0x8000);frees++;}
static void dma_unmap_resource(struct device *dev,u64 dva,size_t size,int dir,int flags)
{assert(dev && dva==0x8000 && size==4096 && !dir && !flags);resource_unmaps++;}
static void clear_bit(unsigned b,unsigned long *p) {*p &= ~(1UL<<b);}
static u32 get_unaligned_le32(const void *p) {u32 v;memcpy(&v,p,4);return v;}
static void put_unaligned_le32(u32 v,void *p) {memcpy(p,&v,4);}
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
    binding = '\n'.join(line for line in handlers.splitlines() if '[202]' in line or '[454]' in line)
    mapping = block(template, 'static bool dcpep_map_piodma(').replace('dev_err(', 'dev_warn_dma(')
    release = block(template, 'static u8 dcpep_cb_release_mem_desc(').replace('dev_warn(', 'dev_warn_release(').replace('dev_err(', 'dev_err_release(')
    physical = block(template, 'static bool is_disp_register(') + '\n' + block(template, 'static struct dcp_map_physical_resp\ndcpep_cb_map_physical(').replace('dev_err(', 'dev_err_release(').replace('dev_warn(', 'dev_warn_release(')
    physical += r"""
static bool trampoline_map_physical(struct apple_dcp *dcp,int tag,void *out,void *in)
{struct dcp_map_physical_resp r=dcpep_cb_map_physical(dcp,in);(void)tag;memcpy(out,&r,sizeof(r));return true;}
"""
    # Assert the table still binds the shared production mapper.
    assert '[452] = trampoline_map_physical,' in handlers
    binding += '\n[452] = trampoline_map_physical,'
    wire = block(desktop, 'struct dcp_unmap_buf_req_v26_6 {')+';\n'
    production = (wire + '\n' + physical + '\n' + release + '\n' + block(desktop, 'static bool trampoline_release_mem_desc_v26_6(') + '\n' + mapping + '\n' + unmap + '\n' + block(desktop, 'static bool trampoline_unmap_piodma_v26_6(') +
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
    __typeof__(*d.desktop) desktop={0};d.desktop=&desktop;
    d.command.depth=1;d.command.header[0]=command.h;
    d.command.callbacks[0]=complete_set_digital_out_mode;
    d.command.cookies[0]=&wait;d.command.output[0]=&command.status;
    d.memdesc[1]=(struct dcp_mem_descriptor){.buf=&d,.dva=0x8000,.size=4096,.map={.sgl=&d}};
    struct dcp_map_buf_req map_request={.buffer=1};struct dcp_map_buf_resp map_reply;
    assert(dcpep_map_piodma(&d,&map_request,&map_reply));
    assert(maps==1 && map_reply.buffer==1 && map_reply.dva==0x8000);
    memset(&packet,0,sizeof(packet));h->in_len=24;
    struct dcp_unmap_buf_req_v26_6 fields={.buffer=1,.id=1,.dva=0x8000};memcpy(packet.data+sizeof(*h),&fields,24);
    case_tag=202;acks=0;
    dcpep_handle_cb(&d,DCP_CONTEXT_CB,h,sizeof(*h)+24,0);
    assert(acks==1 && !d.crashed && !d.channel.depth && unmaps==1);
    assert(!d.memdesc[1].piodma_mapped && d.command.depth==1 && !wait.done);
    /* No firmware response can arrive until the empty callback ACK above. */
    dcpep_handle_ack(&d,DCP_CONTEXT_CMD);
    assert(wait.done && wait.replied && !wait.status && wait.refcount==1 && !d.command.depth);
    /* A later mode can reuse a descriptor after the firmware unmaps it. */
    assert(dcpep_map_piodma(&d,&map_request,&map_reply) && maps==2);
    /* Descriptor release handles both RAM and mapped resources, once. */
    fields.buffer=1;fields.dva=0x8000;memcpy(packet.data+sizeof(*h),&fields,24);
    dcpep_handle_cb(&d,DCP_CONTEXT_CB,h,sizeof(*h)+24,0);
    assert(unmaps==2);
    case_tag=454;h->in_len=4;h->out_len=4;
    put_unaligned_le32(1,packet.data+sizeof(*h));
    memset(packet.data+sizeof(*h)+4,0xa5,4);
    dcpep_handle_cb(&d,DCP_CONTEXT_CB,h,sizeof(*h)+8,0);
    assert(get_unaligned_le32(packet.data+sizeof(*h)+4)==1);
    assert(frees==1 && !d.memdesc_map[0] && !d.memdesc[1].buf && !d.memdesc[1].size);
    dcpep_handle_cb(&d,DCP_CONTEXT_CB,h,sizeof(*h)+8,0);
    assert(!get_unaligned_le32(packet.data+sizeof(*h)+4) && frees==1);
    d.memdesc_map[0]=1;
    struct resource reg={.start=0x123400,.end=0x1243ff};d.disp_registers[0]=&reg;d.nr_disp_registers=1;
    struct dcp_map_physical_req request={.paddr=0x123400,.size=4096};
    struct {struct dcp_packet_header h;struct dcp_map_physical_req in;struct dcp_map_physical_resp out;} __attribute__((packed)) phys={.h={.in_len=24,.out_len=20},.in=request};
    case_tag=452;
    dcpep_handle_cb(&d,DCP_CONTEXT_CB,&phys,sizeof(phys),0);
    assert(physical_maps==1 && phys.out.mem_desc_id==1 && phys.out.dva==0x8000 && phys.out.dva_size==4096);
    assert(d.memdesc_map[0]==3 && d.memdesc[1].reg==0x123400);
    case_tag=454;put_unaligned_le32(1,packet.data+sizeof(*h));
    dcpep_handle_cb(&d,DCP_CONTEXT_CB,h,sizeof(*h)+8,0);
    assert(get_unaligned_le32(packet.data+sizeof(*h)+4)==1 && resource_unmaps==1 && d.memdesc_map[0]==1);
    for(u32 id=4;id<8;id++) {
        put_unaligned_le32(id,packet.data+sizeof(*h));
        dcpep_handle_cb(&d,DCP_CONTEXT_CB,h,sizeof(*h)+8,0);
        assert(!get_unaligned_le32(packet.data+sizeof(*h)+4) && frees==1);
    }
    /* Out-of-range and overflowing physical regions receive no mapping. */
    case_tag=452;phys.in.paddr=0x124000;
    dcpep_handle_cb(&d,DCP_CONTEXT_CB,&phys,sizeof(phys),0);
    assert(!phys.out.dva_size && physical_maps==1);
    phys.in.paddr=~0ULL;phys.in.size=8192;
    dcpep_handle_cb(&d,DCP_CONTEXT_CB,&phys,sizeof(phys),0);
    assert(!phys.out.dva_size && physical_maps==1);
    unsigned before=acks;
    assert(!iomfb_check_callback_v26_6_desktop(454,4,1));
    assert(!iomfb_check_callback_v26_6_desktop(452,23,20));
    /* The declared desktop shape is exact, with no guessed reply bytes. */
    assert(!iomfb_check_callback_v26_6_desktop(202,26,0));
    assert(!iomfb_check_callback_v26_6_desktop(202,24,4));
    case_tag=202;h->in_len=23;h->out_len=0;
    dcpep_handle_cb(&d,DCP_CONTEXT_CB,h,sizeof(*h)+24,0);
    assert(d.crashed && acks==before && unmaps==2);
    return 0;
}
'''


def brightness_takeover(root):
    import display
    source = (root / 'drivers/gpu/drm/apple/dcp_backlight.c').read_text()
    prefix = display.backlight(root).split('static void completed(')[0]
    prefix = prefix.replace('static inline ', 'static inline __attribute__((unused)) ')
    functions = '\n'.join(block(source, marker) for marker in (
        'static bool dcp_backlight_desktop(', 'static int dcp_get_brightness(',
        'static void dcp_backlight_sync_hint(',
        'int dcp_backlight_register(', 'static int dcp_set_brightness(',
        'static bool dcp_backlight_controls_device('))
    return prefix + r'''
#include <stddef.h>
#define READ_ONCE(x) (x)
#define DCP_FIRMWARE_V_26_6_DESKTOP 5
#define DCP_FIRMWARE_H17P 1
#define DCP_IOMFB_METHODS_H17G 7
#define MAX_BRIGHTNESS_PART2 510U
#define BACKLIGHT_PLATFORM 1
#define BACKLIGHT_SCALE_LINEAR 1
#define BL_CORE_SUSPENDED 1
#define BL_CORE_FBBLANK 2
#define DCP_BL_FADE_STEP_MS 16
#define system_dfl_wq NULL
#define IS_ERR(p) false
#define PTR_ERR(p) (-EINVAL)
#define msecs_to_jiffies(n) (n)
#define spin_lock_irqsave(p,f) do {assert(!*(p));*(p)=true;(f)=0;} while(0)
#define spin_unlock_irqrestore(p,f) do {assert(*(p));*(p)=false;(void)(f);} while(0)
struct device {int unused;};
struct backlight_properties {int type,brightness,max_brightness,scale,state;};
struct backlight_device {struct backlight_properties props;void *data;bool ops_lock;};
struct apple_dcp {
    int fw_compat;bool quiescing;
    struct {int iomfb_method_profile;} hw;
    struct {u32 maximum,nits,dac;bool update;struct backlight_device *bl_dev;} brightness;
    struct {bool lock;struct dcp_backlight_state state;unsigned long fade_start;
        int fade_work;void (*kick)(struct apple_dcp *);} backlight;
    struct {bool inherited_brightness_valid;u32 inherited_brightness;} *desktop;
    struct {struct {struct {struct device *dev;} *dev;int mutex;} base;} *crtc;
    struct device *dev;
};
static unsigned long jiffies;
static bool inject_hint,inject_user;
static void mutex_lock(bool *p)
{
    assert(!*p);*p=true;
    if(inject_user) {
        inject_user=false;
        struct backlight_device *bd=(void *)((char *)p - offsetof(struct backlight_device,ops_lock));
        struct apple_dcp *d=bd->data;
        bd->props.brightness=450;
        assert(!dcp_bl_request(&d->backlight.state,450,false,false));
    }
}
static void mutex_unlock(bool *p) {assert(*p);*p=false;}
static struct backlight_device registered;
static const int dcp_backlight_ops;
static void *bl_get_data(struct backlight_device *bd) {return bd->data;}
static bool iomfb_is_m4(struct apple_dcp *d) {(void)d;return false;}
bool dcp_backlight_active(struct apple_dcp *d) {(void)d;return false;}
static void dcp_backlight_desktop_kick(struct apple_dcp *d) {(void)d;}
static void dcp_backlight_kick(struct apple_dcp *d) {(void)d;}
static unsigned fades;
static void queue_delayed_work(void *q,int *work,unsigned delay)
{assert(!q && delay==16);(void)work;fades++;}
static struct backlight_device *devm_backlight_device_register(struct device *dev,
    const char *name,struct device *parent,void *data,const int *ops,
    const struct backlight_properties *props)
{(void)dev;(void)name;(void)parent;assert(ops==&dcp_backlight_ops);
 registered=(struct backlight_device){.props=*props,.data=data};
 if(inject_hint) {inject_hint=false;struct apple_dcp *d=data;assert(dcp_bl_seed(&d->backlight.state,180));}
 return &registered;}
static int backlight_get_brightness(struct backlight_device *bd)
{return bd->props.state?0:bd->props.brightness;}
static bool backlight_is_blank(struct backlight_device *bd) {return !!bd->props.state;}
static u32 calculate_dac(struct apple_dcp *d,int nits) {(void)d;(void)nits;assert(false);return 0;}
static int drm_modeset_lock_single_interruptible(int *p) {(void)p;assert(false);return 0;}
static void drm_modeset_unlock(int *p) {(void)p;assert(false);}
static int dcp_backlight_update(struct apple_dcp *d) {(void)d;assert(false);return 0;}
''' + functions + r'''
int main(void)
{
    struct apple_dcp d={.fw_compat=5,.brightness={.maximum=600}};
    __typeof__(*d.desktop) saved={0};d.desktop=&saved;
    assert(!dcp_backlight_register(&d));
    assert(registered.props.brightness==300 && registered.props.max_brightness==600);
    assert(dcp_get_brightness(&registered)==300);
    assert(!dcp_backlight_controls_device(&registered,NULL));
    /* A save/restore client echoes the exposed value, not a new target. */
    assert(!dcp_set_brightness(&registered));
    assert(!d.backlight.state.controlled && !d.backlight.state.dirty);
    registered.props.state=BL_CORE_SUSPENDED|BL_CORE_FBBLANK;
    assert(!dcp_set_brightness(&registered));
    registered.props.state=0;assert(!dcp_set_brightness(&registered));
    assert(!d.backlight.state.controlled && !d.backlight.state.dirty);
    assert(dcp_get_brightness(&registered)==300);
    /* A different explicit target takes over the unknown inherited level. */
    registered.props.brightness=250;assert(!dcp_set_brightness(&registered));
    assert(d.backlight.state.controlled && d.backlight.state.fading && !d.backlight.state.dirty && fades==1);
    assert(!dcp_bl_fade_step(&d.backlight.state,250,250));
    assert(dcp_backlight_controls_device(&registered,NULL));
    struct dcp_backlight_present present;
    assert(!dcp_bl_prepare(&d.backlight.state,true,&present) && present.nits==250);
    assert(dcp_get_brightness(&registered)==250);
    assert(dcp_bl_complete(&d.backlight.state,present.sequence,true));
    assert(dcp_get_brightness(&registered)==250);
    /* Even the former midpoint is an ordinary faded target after takeover. */
    registered.props.brightness=300;assert(!dcp_set_brightness(&registered));
    assert(d.backlight.state.fading && fades==2 && d.backlight.state.target==300);
    /* A real loader hint seeds registration without needing a present. */
    d.brightness.bl_dev=NULL;d.backlight.state=(struct dcp_backlight_state){0};
    inject_hint=true;
    assert(!dcp_backlight_register(&d) && registered.props.brightness==180);
    assert(dcp_get_brightness(&registered)==180);
    assert(dcp_backlight_controls_device(&registered,NULL));
    /* A user write racing the late-hint notification keeps its target. */
    inject_user=true;dcp_backlight_sync_hint(&d);
    assert(d.backlight.state.controlled && d.backlight.state.target==450);
    assert(registered.props.brightness==450 && !registered.ops_lock);
    return 0;
}
'''


def modeset_unknown(root):
    template = (root / 'drivers/gpu/drm/apple/iomfb_template.c').read_text()
    unit = modeset_unmap(root)
    helper = block(template, 'static bool dcp_modeset_callback_failed(')
    # Keep the real modeset completion and its callback-error check. The
    # adaptive retry boundary must never be reached after an unknown callback.
    helper += r'''
struct dcp_modeset_cookie {struct dcp_wait_cookie wait;bool vrr;};
static void dcp_modeset_fixed_fallback(struct apple_dcp *d,struct dcp_modeset_cookie *m)
{(void)d;(void)m;assert(false);}
''' + block(template, 'static void dcp_modeset_actual_done(')
    unit = unit.replace('int main(void)', helper + '\nint main(void)')
    tests = r'''
    /* A fresh channel has an A413 outstanding; inject a valid but unknown D. */
    d.crashed=false;desktop.modeset_active=true;desktop.modeset_callback_error=false;
    struct dcp_modeset_cookie mode={.wait={.status=~0U,.refcount=2},.vrr=true};
    d.command.depth=1;d.command.header[0]=command.h;
    d.command.callbacks[0]=dcp_modeset_actual_done;
    d.command.cookies[0]=&mode;d.command.output[0]=&command.status;
    case_tag=499;h->in_len=4;h->out_len=4;
    memset(packet.data+sizeof(*h)+4,0xa5,4);before=acks;
    dcpep_handle_cb(&d,DCP_CONTEXT_CB,h,sizeof(*h)+8,0);
    assert(acks==before+1 && !d.crashed && !d.channel.depth);
    assert(!get_unaligned_le32(packet.data+sizeof(*h)+4));
    assert(desktop.modeset_callback_error && d.command.depth==1 && !mode.wait.done);
    /* Draining the real ACK fails the set, even if firmware reports success. */
    dcpep_handle_ack(&d,DCP_CONTEXT_CMD);
    assert(mode.wait.done && !mode.wait.replied && mode.wait.status==~0U);
    assert(mode.wait.refcount==1 && !d.command.depth);
    /* The next fixed modeset is independent and completes normally. */
    desktop.modeset_active=false;desktop.modeset_callback_error=false;
    mode=(struct dcp_modeset_cookie){.wait={.status=~0U,.refcount=2}};
    d.command.depth=1;d.command.header[0]=command.h;
    d.command.callbacks[0]=dcp_modeset_actual_done;
    d.command.cookies[0]=&mode;d.command.output[0]=&command.status;
    dcpep_handle_ack(&d,DCP_CONTEXT_CMD);
    assert(mode.wait.done && mode.wait.replied && !mode.wait.status);
    assert(!d.crashed && !d.command.depth && !d.channel.depth);
'''
    return unit.replace('    return 0;\n}', tests + '    return 0;\n}')


def panel_identity(root):
    import struct
    import rate
    f = rate.parser_fixture(root)
    attributes = {'MaxHorizontalImageSize': 0, 'MaxVerticalImageSize': 0,
                  'ProductAttributes': {'ManufacturerID': 'TST', 'ProductID': 42,
                                        'ProductName': 'Synthetic Internal Panel',
                                        'SerialNumber': 0x12345678}}
    raw = bytearray(struct.pack('<I', 0xd3)); f['wire'](attributes, raw)
    code = (f['prefix'] + f['metadata'] + f['epoch'].replace('static inline ', 'static inline __attribute__((unused)) ') + f['header'] +
            f['edid_header'] + f['parser'] + f['stubs'] + f['builder'])
    source = (root / 'drivers/gpu/drm/apple/dcp.c').read_text()
    helpers = '\n'.join(block(source, name) for name in (
        'void dcp_panel_metadata_replace(', 'bool dcp_panel_metadata_current(',
        'const struct drm_edid *dcp_panel_edid_snapshot('))
    return code + r'''
#define DCP_FIRMWARE_V_26_6_DESKTOP 5
#define spin_lock_irqsave(p,f) do {assert(!*(p));*(p)=true;(f)=0;} while(0)
#define spin_unlock_irqrestore(p,f) do {assert(*(p));*(p)=false;(void)(f);} while(0)
struct apple_dcp {
    int fw_compat;bool has_panel;struct {bool lock;} metadata;
    struct {struct dcp_display_metadata panel_metadata;u64 panel_metadata_generation;bool panel_metadata_valid;} *desktop;
    struct {u32 width_mm,height_mm;} panel;void *connector;
};
static unsigned notifications;
static bool dcp_has_panel(struct apple_dcp *d) {return d->has_panel;}
static void dcp_queue_hotplug(void *con) {assert(con);notifications++;}
''' + helpers + '\nstatic const u8 attributes[]={'+','.join(map(str,raw))+'};\n' + r'''
int main(void)
{
    struct dcp_parse_ctx ctx;
    struct dcp_display_metadata metadata;
    assert(!parse(attributes,sizeof(attributes),&ctx));
    assert(!parse_panel_metadata(&ctx,&metadata));
    assert(!strcmp(metadata.manufacturer,"TST") && metadata.product==42 && metadata.serial==0x12345678);
    assert(!strcmp(metadata.name,"Synthetic Int"));
    /* No color fields, date or EDID-representable timing is required. */
    struct apple_dcp d={.fw_compat=5,.has_panel=true,.panel={345,223},.connector=&d};
    __typeof__(*d.desktop) desktop={0};d.desktop=&desktop;
    u64 generation=99;
    assert(IS_ERR(dcp_panel_edid_snapshot(&d,&generation)));
    dcp_panel_metadata_replace(&d,&metadata);
    assert(notifications==1 && desktop.panel_metadata_valid);
    const struct drm_edid *edid=dcp_panel_edid_snapshot(&d,&generation);
    assert(!IS_ERR(edid) && drm_edid_valid(edid) && dcp_panel_metadata_current(&d,generation));
    const u8 *bytes=(const void *)&edid->raw;
    assert(bytes[8]==0x52 && bytes[9]==0x74 && bytes[10]==42 && !bytes[11]);
    assert(bytes[12]==0x78 && bytes[13]==0x56 && bytes[14]==0x34 && bytes[15]==0x12);
    assert(bytes[18]==1 && bytes[19]==3 && bytes[21]==35 && bytes[22]==22 && bytes[23]==0xff);
    assert(bytes[54+3]==EDID_DETAIL_MONITOR_NAME && bytes[72+3]==EDID_DETAIL_MONITOR_SERIAL);
    assert(!memcmp(bytes+72+5,"12345678\n",9));
    drm_edid_free(edid);
    dcp_panel_metadata_replace(&d,NULL);
    assert(!dcp_panel_metadata_current(&d,generation));
    assert(IS_ERR(dcp_panel_edid_snapshot(&d,&generation)));
    /* Another firmware/profile cannot publish a desktop panel identity. */
    d.fw_compat=2;dcp_panel_metadata_replace(&d,&metadata);
    assert(!desktop.panel_metadata_valid);
    metadata.manufacturer[0]='?';assert(IS_ERR(dcp_panel_edid(&metadata,345,223)));
    return 0;
}
'''
