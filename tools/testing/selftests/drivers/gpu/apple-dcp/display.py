# SPDX-License-Identifier: GPL-2.0-only OR MIT
# Copyright 2026 Ryan Murray
"""Internal panel policy and real TimingElements parser, without hardware."""
import copy
import struct
from common import block
import rate


def backlight(root):
    header = (root / 'drivers/gpu/drm/apple/dcp_backlight.h').read_text()
    header = '\n'.join(line for line in header.splitlines()
                       if not line.startswith('#include'))
    return r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <limits.h>
#include <errno.h>
typedef uint32_t u32;
typedef uint64_t u64;
typedef uint8_t u8;
#define min(a,b) ((a)<(b)?(a):(b))
#define mul_u32_u32(a,b) ((u64)(a)*(b))
#define div_u64(a,b) ((a)/(b))
''' + header + r'''
static void completed(struct dcp_backlight_state *s, struct dcp_backlight_swap *p,
                      u32 id, bool early)
{
    u32 old=s->actual;
    if(early) {
        assert(!dcp_bl_swap_finish(s,p,id,false,true));
        assert(s->actual==old && s->in_flight);
        assert(dcp_bl_swap_finish(s,p,id,true,true));
    } else {
        assert(!dcp_bl_swap_finish(s,p,id,true,true));
        assert(s->actual==old && s->in_flight);
        assert(dcp_bl_swap_finish(s,p,id,false,true));
    }
    assert(!dcp_bl_swap_finish(s,p,id,false,true));
}
int main(void)
{
    struct dcp_backlight_state s;
    struct dcp_backlight_swap p={0};
    u32 id=1, nits;
    assert(!dcp_bl_takeover_nits(600,600000,&nits) && nits==600);
    /* A registration default must never change the loader's visible level. */
    assert(!dcp_bl_init(&s,600,false,0,true,250)); s.fade=true;
    assert(!s.dirty && !s.level_known);
    assert(dcp_bl_swap_prepare(&s,&p,id,true)==-EALREADY);
    assert(!dcp_bl_request(&s,250,false,false));
    assert(!s.fading && s.dirty);
    assert(dcp_bl_swap_prepare(&s,&p,id,false)==-ENODATA);
    assert(!dcp_bl_swap_prepare(&s,&p,id,true));
    completed(&s,&p,id++,true);
    assert(s.actual==250 && s.level_known);
    assert(!dcp_bl_seed(&s,300));
    /* Same state as a slider request or an ALS retarget through backlight. */
    assert(!dcp_bl_request(&s,600,false,false) && s.fading);
    for(u32 t=16;t<250;t+=16) {
        u32 before=s.level;
        assert(dcp_bl_fade_step(&s,t,250));
        assert(s.level>=before && s.level<600);
        if(t==16) {
            assert(!dcp_bl_swap_prepare(&s,&p,id,true));
            assert(dcp_bl_swap_finish(&s,&p,id++,true,false));
            assert(s.actual==250 && s.dirty && dcp_bl_retry_delay(&s)==100);
        }
    }
    assert(!dcp_bl_fade_step(&s,250,250));
    assert(!dcp_bl_swap_prepare(&s,&p,id,true));
    assert(!dcp_bl_swap_finish(&s,&p,id+100,false,true));
    completed(&s,&p,id++,false); assert(s.actual==600);
    assert(dcp_bl_request(&s,601,false,false)==-ERANGE);
    assert(!dcp_bl_request(&s,0,false,false));
    assert(dcp_bl_fade_step(&s,125,250) && s.level==300);
    assert(!dcp_bl_request(&s,100,false,false) && s.fade_from==300);
    assert(dcp_bl_fade_step(&s,125,250) && s.level==200);
    assert(!dcp_bl_request(&s,100,true,false));
    assert(!s.fading && dcp_bl_effective(&s)==0);
    assert(!dcp_bl_request(&s,450,true,false) && dcp_bl_effective(&s)==0);
    assert(!dcp_bl_request(&s,450,false,false) && s.level==450);
    assert(!dcp_bl_request(&s,0,false,true) && dcp_bl_effective(&s)==0);
    assert(!dcp_bl_request(&s,450,false,false) && s.level==450);
    assert(!dcp_bl_dpms(&s,false) && dcp_bl_effective(&s)==0);
    assert(!dcp_bl_dpms(&s,true) && dcp_bl_effective(&s)==450);
    assert(!dcp_bl_resend(&s));
    return 0;
}
'''


def modes(root):
    f = rate.parser_fixture(root)
    # Use the exact production parser and public serializer already used by rate.
    parser = f['parser']
    prefix = (f['prefix'] + f['epoch'] + f['metadata'] + f['header']).replace('static inline ', 'static inline __attribute__((unused)) ')
    baseline = copy.deepcopy(f['timing_fixture'][0])
    checks = []
    blobs = []

    def case(elements, expected, ranges=None):
        raw = bytearray(struct.pack('<I', 0xd3))
        f['wire'](elements, raw)
        i = len(blobs)
        blobs.append('static const unsigned char b%u[]={%s};' %
                     (i, ','.join(map(str, raw))))
        check = (f'{{ struct dcp_parse_ctx c; unsigned n=99; '
                 f'assert(!parse(b{i},sizeof(b{i}),&c)); '
                 'struct dcp_display_mode *m=enumerate_modes(&c,&n,355,230,0,true,false); '
                 f'assert(!IS_ERR(m) && n=={len(expected)});')
        for j, hz in enumerate(expected):
            check += (f'assert(m[{j}].mode.clock=={round(2200*1125*hz/1000)}); '
                      f'assert(m[{j}].timing_mode_id=={elements[j]["ID"]}); '
                      f'assert(m[{j}].mode.htotal==2200 && m[{j}].mode.vtotal==1125); '
                      f'assert(m[{j}].mode.flags==(DRM_MODE_FLAG_PHSYNC|DRM_MODE_FLAG_PVSYNC)); ')
        for j, hz in enumerate(expected):
            if hz >= 119.88:
                check += f'assert(m[{j}].needs_timestamps); '
        if ranges:
            for j, (lo, hi) in enumerate(ranges):
                check += f'assert(m[{j}].vrr=={int(bool(lo))}); '
                if lo:
                    check += f'assert(m[{j}].min_vrr=={lo} && m[{j}].max_vrr=={hi}); '
        checks.append(check + 'free(m); }')

    supported = []
    # Synthetic rates exercise catalog handling, not a claim about a panel dump.
    for i, hz in enumerate((120, 60, 59.94, 50, 48, 47.952)):
        m = copy.deepcopy(baseline)
        m['ID'] = 100+i
        m['VerticalAttributes']['PreciseSyncRate'] = round(hz*65536)
        supported.append(m)
    case(supported, (120, 60, 59.94, 50, 48, 47.952),
         [(24<<16, 120<<16)] + [(0,0)]*5)
    for hz in (119.88, 120, 120.01):
        m=copy.deepcopy(supported[0]); m['VerticalAttributes']['PreciseSyncRate']=round(hz*65536)
        case([m], [hz], [(24<<16, round(hz*65536))])
    for lo, hi, valid in ((48<<16,120<<16,True), (0,120<<16,False),
                          (60<<16,0,False), (0,0,False), (120<<16,24<<16,False),
                          (24<<16,144<<16,False), (120<<16,120<<16,False)):
        m=copy.deepcopy(supported[0]); m['MinimumVariableRefreshRate']=lo; m['MaximumVariableRefreshRate']=hi
        case([m],[120],[(lo,hi) if valid else (0,0)])
    m=copy.deepcopy(supported[0]);m['MinimumVariableRefreshRate']=24<<16
    m=f['ObjectPairs'](list(m.items())+[('MinimumVariableRefreshRate',48<<16)])
    # Check duplicates against the parser directly without dict indexing in case().
    raw=bytearray(struct.pack('<I',0xd3));f['wire']([m],raw)
    blobs.append('static const unsigned char dup[]={%s};' % ','.join(map(str,raw)))
    checks.append('{struct dcp_parse_ctx c;unsigned n;assert(!parse(dup,sizeof(dup),&c));'
                  'struct dcp_display_mode *m=enumerate_modes(&c,&n,355,230,0,true,false);'
                  'assert(!IS_ERR(m) && n==1 && !m[0].vrr);free(m);}')
    # Bad geometry and virtual modes are still rejected.
    for field, value in (('Total', 1000), ('FrontPorch', 65536)):
        m=copy.deepcopy(supported[0]);m['HorizontalAttributes'][field]=value
        case([m],[])
    m=copy.deepcopy(supported[0]);m['IsVirtual']=True;case([m],[])
    return prefix + parser + '\n'.join(blobs) + '\nint main(void){' + '\n'.join(checks) + 'return 0;}'


def refresh(root):
    h=(root/'drivers/gpu/drm/apple/dcp-refresh.h').read_text().replace('#include <linux/types.h>','')
    return r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
typedef uint32_t u32;
typedef uint64_t u64;
''' + h + r'''
int main(void) {
    u32 lo=0,hi=0;
    assert(dcp_refresh_range(120U<<16,0,0,true,&lo,&hi));
    assert(lo==24U<<16 && hi==120U<<16);
    assert(!dcp_refresh_range(120U<<16,0,0,false,&lo,&hi));
    assert(!dcp_refresh_range(60U<<16,0,0,true,&lo,&hi));
    assert(!dcp_refresh_range(120U<<16,0,120U<<16,true,&lo,&hi));
    assert(!dcp_refresh_range(120U<<16,120U<<16,24U<<16,true,&lo,&hi));
    assert(!dcp_refresh_range(120U<<16,24U<<16,144U<<16,true,&lo,&hi));
    assert(dcp_desktop_present_deadline(true,true)==120);
    assert(dcp_desktop_present_deadline(true,false)==0);
    assert(dcp_desktop_present_deadline(false,true)==0);
    return 0;
}
'''


def adaptive(root):
    source=(root/'drivers/gpu/drm/apple/iomfb_template.c').read_text()
    funcs='\n'.join(block(source, marker) for marker in (
        'static void dcp_modeset_fixed_fallback(',
        'static void dcp_modeset_actual_done(',
        'static void dcp_modeset_after_actual_info(',
        'static void dcp_modeset_after_bootstrap(',
        'static void dcp_modeset_after_bootstrap_info(',
        'static void dcp_modeset_select(',
        'static void dcp_modeset_sync_done(',
        'static void dcp_modeset_sync('))
    cookie=block(source,'struct dcp_modeset_cookie {')+';\n'
    main=(root/'drivers/gpu/drm/apple/iomfb.c').read_text()
    gate=block(main,'bool dcp_desktop_vrr_supported(') + block(main,'int dcp_desktop_vrr_check(')
    return r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <errno.h>
typedef uint32_t u32;
typedef uint64_t u64;
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
#define DCP_FIRMWARE_V_26_6_DESKTOP 5
#define IOMFBPARAM_ADAPTIVE_SYNC 14
#define dev_warn(...) ((void)0)
struct dcp_wait_cookie { u32 status; bool done,replied; };
struct dcp_set_digital_out_mode_req {u32 color_mode_id,timing_mode_id;};
struct dcp_set_parameter_dcp { u32 param; u64 value[4]; u32 count; };
struct apple_dcp {void *dev;int fw_compat;bool main_display,panel;struct {bool vrr_failed;} *desktop;};
static bool t6041_vrr;
struct drm_display_mode {int id;};
struct drm_crtc_state {bool vrr_enabled;struct drm_display_mode mode;};
struct dcp_display_mode {bool vrr;};
static bool lookup_mode(struct apple_dcp *d,struct drm_display_mode *m,struct dcp_display_mode *out)
{out->vrr=m->id==120;return m->id==60 || m->id==120;}
static bool dcp_has_panel(struct apple_dcp *d) {return d->panel;}
static u32 get_unaligned_le32(const void *p) {u32 v;memcpy(&v,p,4);return v;}
typedef void (*callback)(struct apple_dcp *,void *,void *);
static callback pending;
static void *cookie_pending;
static unsigned kind, parameters,infos,modes;
static struct dcp_set_parameter_dcp parameter;
static struct dcp_set_digital_out_mode_req requested;
static void dcp_modeset_select(struct apple_dcp *,void *,void *);
static void dcp_modeset_sync(struct apple_dcp *,void *);
static void dcp_set_parameter_dcp(struct apple_dcp *d,bool oob,
    struct dcp_set_parameter_dcp *p,callback cb,void *c)
{assert(!pending && !oob);parameter=*p;pending=cb;cookie_pending=c;kind=1;parameters++;}
static void dcp_get_mode_info(struct apple_dcp *d,const struct dcp_set_digital_out_mode_req *m,callback cb,void *c)
{assert(!pending);requested=*m;pending=cb;cookie_pending=c;kind=2;infos++;}
static void dcp_set_digital_out_mode(struct apple_dcp *d,bool oob,
    struct dcp_set_digital_out_mode_req *m,callback cb,void *c)
{assert(!pending && !oob);requested=*m;pending=cb;cookie_pending=c;kind=3;modes++;}
static void complete_set_digital_out_mode(struct apple_dcp *d,void *p,void *c)
{struct dcp_wait_cookie *w=c;w->done=true;w->replied=!!p;if(p)w->status=get_unaligned_le32(p);}
''' + cookie + gate + funcs + r'''
static void reply(struct apple_dcp *d,unsigned expected,u32 *status)
{assert(kind==expected && pending);callback cb=pending;void *c=cookie_pending;pending=NULL;cb(d,status,c);}
static void initialize(struct dcp_modeset_cookie *m)
{memset(m,0,sizeof(*m));m->vrr=true;m->min_vrr=24U<<16;m->actual=(struct dcp_set_digital_out_mode_req){11,12};m->bootstrap=(struct dcp_set_digital_out_mode_req){13,12};}
static void selected(struct apple_dcp *d,struct dcp_modeset_cookie *m)
{u32 zero=0;reply(d,2,&zero);assert(requested.color_mode_id==11);reply(d,3,&zero);assert(m->wait.done && m->wait.replied && !m->wait.status);}
int main(void)
{
    struct apple_dcp d={.fw_compat=DCP_FIRMWARE_V_26_6_DESKTOP,.main_display=true,.panel=true};
    __typeof__(*d.desktop) desktop={0};d.desktop=&desktop;
    struct drm_crtc_state state={.vrr_enabled=true,.mode={120}};
    assert(dcp_desktop_vrr_check(&d,&state)==-EINVAL);
    assert(!dcp_desktop_vrr_supported(&d));t6041_vrr=true;
    assert(!dcp_desktop_vrr_check(&d,&state));
    state.mode.id=60;assert(dcp_desktop_vrr_check(&d,&state)==-EINVAL);
    state.vrr_enabled=false;assert(!dcp_desktop_vrr_check(&d,&state));
    state.vrr_enabled=true;state.mode.id=120;
    assert(dcp_desktop_vrr_supported(&d));
    d.main_display=false;assert(!dcp_desktop_vrr_supported(&d));d.main_display=true;
    d.panel=false;assert(!dcp_desktop_vrr_supported(&d));d.panel=true;
    d.fw_compat=3;assert(!dcp_desktop_vrr_supported(&d));d.fw_compat=DCP_FIRMWARE_V_26_6_DESKTOP;
    struct dcp_modeset_cookie m;u32 zero=0,error=1;
    initialize(&m);dcp_modeset_sync(&d,&m);
    assert(parameter.param==14 && parameter.count==3 && parameter.value[0]==24U<<16);
    assert(!parameter.value[1] && !parameter.value[2] && parameter.value[3]==0xaaaaaaaaaaaaaaaaULL);
    reply(&d,1,&zero);selected(&d,&m);assert(m.vrr && !desktop.vrr_failed);
    /* Rejected enable is cleared before a fixed timing is selected. */
    initialize(&m);dcp_modeset_sync(&d,&m);reply(&d,1,&error);
    assert(desktop.vrr_failed && !dcp_desktop_vrr_supported(&d) && !m.vrr && !parameter.value[0]);
    assert(!dcp_desktop_vrr_check(&d,&state)); /* Recovery re-applies fixed refresh. */
    reply(&d,1,&zero);selected(&d,&m);
    /* A rejected modeset gets one fixed-refresh retry. */
    desktop.vrr_failed=false;initialize(&m);dcp_modeset_sync(&d,&m);
    reply(&d,1,&zero);reply(&d,2,&zero);reply(&d,3,&error);
    assert(!m.vrr && desktop.vrr_failed && kind==1 && !parameter.value[0]);
    reply(&d,1,&zero);selected(&d,&m);
    /* Failed disable and absent replies must stop, without claiming success. */
    initialize(&m);dcp_modeset_sync(&d,&m);reply(&d,1,&error);reply(&d,1,&error);
    assert(m.wait.done && m.wait.status && !pending);
    initialize(&m);dcp_modeset_sync(&d,&m);reply(&d,1,NULL);
    assert(m.wait.done && !m.wait.replied && !pending);
    /* Bootstrap keeps the DCP's actual color/timing identities. */
    desktop.vrr_failed=false;initialize(&m);m.use_bootstrap=true;
    dcp_modeset_sync(&d,&m);reply(&d,1,&zero);
    assert(requested.color_mode_id==13 && requested.timing_mode_id==12);
    reply(&d,2,&zero);reply(&d,3,&zero);selected(&d,&m);
    assert(parameters && infos && modes);
    return 0;
}
'''


def takeover(root):
    prefix=backlight(root).split('static void completed(')[0]
    prefix=prefix.replace('static inline ', 'static inline __attribute__((unused)) ')
    function=block((root/'drivers/gpu/drm/apple/dcp_backlight.c').read_text(),
                   'int dcp_backlight_takeover(')
    return prefix + r'''
#define DCP_FIRMWARE_V_26_6_DESKTOP 5
#define READ_ONCE(x) (x)
#define spin_lock_irqsave(p,f) do {assert(!*(p));*(p)=true;(f)=0;} while(0)
#define spin_unlock_irqrestore(p,f) do {assert(*(p));*(p)=false;(void)(f);} while(0)
struct apple_dcp {
    int fw_compat;
    struct {u32 maximum;} brightness;
    struct {bool lock;struct dcp_backlight_state state;} backlight;
    struct {bool inherited_brightness_valid;u32 inherited_brightness;} *desktop;
};
static unsigned legacy;
bool dcp_backlight_active(struct apple_dcp *d) {return d->fw_compat==1 && d->backlight.state.ready;}
static int iomfb_configure_backlight_h17p(struct apple_dcp *d,u32 max,bool valid,u32 nits,bool fallback,u32 guessed)
{assert(max==600 && valid && nits==100 && !fallback && !guessed);legacy++;return 0;}
''' + function + r'''
int main(void) {
    struct apple_dcp d={.fw_compat=5,.brightness={600}};
    __typeof__(*d.desktop) saved={0};d.desktop=&saved;
    assert(!dcp_backlight_takeover(&d,0));
    assert(saved.inherited_brightness_valid && !saved.inherited_brightness && !legacy);
    assert(!dcp_backlight_takeover(&d,500000) && !saved.inherited_brightness);
    saved.inherited_brightness_valid=false;
    assert(dcp_backlight_takeover(&d,1300000)==-ERANGE && !saved.inherited_brightness_valid);
    assert(!dcp_backlight_takeover(&d,700000) && saved.inherited_brightness==600);
    d.backlight.state.ready=true; saved.inherited_brightness_valid=false;
    assert(!dcp_backlight_takeover(&d,100000) && !saved.inherited_brightness_valid);
    d.fw_compat=1;d.backlight.state.ready=false;
    assert(!dcp_backlight_takeover(&d,100000) && legacy==1);
    return 0;
}
'''


def watchdog(root):
    source=(root/'drivers/gpu/drm/apple/dcp.c').read_text()
    production='\n'.join(block(source, marker) for marker in (
        'bool dcp_desktop_present_complete(',
        'VISIBLE_IF_KUNIT void dcp_swap_watchdog(',
        'void dcp_swap_watchdog_arm(',
        'void dcp_swap_watchdog_complete('))
    definitions='\n'.join(line for line in source.splitlines()
                          if line.startswith('#define DCP_SWAP_WATCHDOG_'))
    return r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
typedef uint32_t u32;
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
#define xchg(p,v) __atomic_exchange_n((p),(v),__ATOMIC_SEQ_CST)
#define VISIBLE_IF_KUNIT
#define DCP_FIRMWARE_V_26_6_DESKTOP 5
#define dev_warn(...) ((void)0)
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define to_delayed_work(p) container_of(p,struct delayed_work,work)
#define msecs_to_jiffies(n) (n)
#define time_before(a,b) ((long)((a)-(b))<0)
#define system_dfl_wq NULL
static unsigned long jiffies;
struct work_struct {unsigned unused;};
struct delayed_work {struct work_struct work;};
struct apple_dcp {
    int fw_compat;bool vrr_enabled,typec;
    struct {u32 present_id;bool present_pending,vrr_failed;} *desktop;
    struct {bool valid;} mode_state;
    struct delayed_work swap_watchdog_wq;
    unsigned long swap_watchdog_deadline;
    unsigned swap_watchdog_retrains;
    void *crtc,*connector,*dev;
};
static unsigned scheduled,cancelled,vblanks,hotplugs,unarmed,rejected;
static bool allow_retire=true;
static bool iomfb_retire_dropped_present_h17p(struct apple_dcp *d) {return allow_retire;}
static void dcp_unarm_retained_framebuffers(struct apple_dcp *d,u32 id)
{assert(id==d->desktop->present_id);unarmed++;}
static void dcp_backlight_desktop_finish(struct apple_dcp *d,u32 id,bool reply,bool accepted)
{assert(id==d->desktop->present_id && reply && !accepted);rejected++;}
static void dcp_mode_invalidate(__typeof__(((struct apple_dcp *)0)->mode_state) *m) {m->valid=false;}
static void dcp_drm_crtc_vblank(void *c) {vblanks++;}
static void dcp_queue_hotplug(void *c) {hotplugs++;}
static bool dcp_is_typec_output(struct apple_dcp *d) {return d->typec;}
static void mod_delayed_work(void *q,struct delayed_work *w,unsigned long delay)
{assert(delay==1000);scheduled++;}
static void cancel_delayed_work(struct delayed_work *w) {cancelled++;}
''' + definitions + '\n' + production + r'''
int main(void) {
    struct apple_dcp d={.fw_compat=5,.vrr_enabled=true,.mode_state={true},.connector=(void *)1};
    __typeof__(*d.desktop) state={.present_id=42,.present_pending=true};d.desktop=&state;
    dcp_swap_watchdog_arm(&d);assert(scheduled==1 && d.swap_watchdog_deadline==1000);
    jiffies=999;dcp_swap_watchdog(&d.swap_watchdog_wq.work);
    assert(d.mode_state.valid && !hotplugs && !unarmed && state.present_pending);
    assert(!dcp_desktop_present_complete(&d,41) && state.present_pending);
    assert(dcp_desktop_present_complete(&d,42) && !state.present_pending);
    assert(!dcp_desktop_present_complete(&d,42));
    dcp_swap_watchdog_complete(&d);assert(cancelled==1);
    jiffies=1000;dcp_swap_watchdog(&d.swap_watchdog_wq.work);assert(!hotplugs);
    /* Expiry owns this dropped swap, retains its buffers and triggers reset. */
    state.present_id=43;state.present_pending=true;
    dcp_swap_watchdog(&d.swap_watchdog_wq.work);
    assert(state.vrr_failed && !d.vrr_enabled && !state.present_pending);
    assert(!d.mode_state.valid && hotplugs==1 && vblanks==1 && unarmed==1 && rejected==1);
    assert(!dcp_desktop_present_complete(&d,43));
    /* A late completion cannot finish the new fixed-refresh present. */
    state.present_id=44;state.present_pending=true;
    assert(!dcp_desktop_present_complete(&d,43) && state.present_pending);
    assert(dcp_desktop_present_complete(&d,44));
    unsigned before=scheduled;dcp_swap_watchdog_arm(&d);assert(scheduled==before);
    /* The established external watchdog remains armed on a Type-C output. */
    d.fw_compat=1;d.typec=true;dcp_swap_watchdog_arm(&d);assert(scheduled==before+1);
    allow_retire=false;d.mode_state.valid=true;
    dcp_swap_watchdog(&d.swap_watchdog_wq.work);assert(d.mode_state.valid && hotplugs==1);
    return 0;
}
'''
