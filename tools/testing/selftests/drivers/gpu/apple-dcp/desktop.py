# SPDX-License-Identifier: GPL-2.0-only OR MIT
# Copyright 2026 Ryan Murray
"""Desktop modeset callbacks through the production dispatcher and DMA policy."""
from common import block


def brightness_takeover(root):
    import display
    source = (root / 'drivers/gpu/drm/apple/dcp_backlight.c').read_text()
    prefix = display.backlight(root).split('static void completed(')[0]
    prefix = prefix.replace('static inline ', 'static inline __attribute__((unused)) ')
    functions = '\n'.join(block(source, marker) for marker in (
        'static bool dcp_backlight_desktop(', 'static int dcp_get_brightness(',
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
struct backlight_device {struct backlight_properties props;void *data;};
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
 registered=(struct backlight_device){.props=*props,.data=data};return &registered;}
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
    assert(dcp_get_brightness(&registered)==-ENODATA);
    assert(!dcp_backlight_controls_device(&registered,NULL));
    /* A save/restore client echoes the exposed value, not a new target. */
    assert(!dcp_set_brightness(&registered));
    assert(!d.backlight.state.controlled && !d.backlight.state.dirty);
    registered.props.state=BL_CORE_SUSPENDED|BL_CORE_FBBLANK;
    assert(!dcp_set_brightness(&registered));
    registered.props.state=0;assert(!dcp_set_brightness(&registered));
    assert(!d.backlight.state.controlled && !d.backlight.state.dirty);
    assert(dcp_get_brightness(&registered)==-ENODATA);
    /* A different explicit target takes over the unknown inherited level. */
    registered.props.brightness=250;assert(!dcp_set_brightness(&registered));
    assert(d.backlight.state.controlled && d.backlight.state.dirty && !fades);
    assert(dcp_backlight_controls_device(&registered,NULL));
    struct dcp_backlight_present present;
    assert(!dcp_bl_prepare(&d.backlight.state,true,&present) && present.nits==250);
    assert(dcp_get_brightness(&registered)==-ENODATA);
    assert(dcp_bl_complete(&d.backlight.state,present.sequence,true));
    assert(dcp_get_brightness(&registered)==250);
    /* Even the former midpoint is an ordinary faded target after takeover. */
    registered.props.brightness=300;assert(!dcp_set_brightness(&registered));
    assert(d.backlight.state.fading && fades==1 && d.backlight.state.target==300);
    /* A real loader hint seeds registration without needing a present. */
    d.brightness.bl_dev=NULL;d.backlight.state=(struct dcp_backlight_state){0};
    saved.inherited_brightness_valid=true;saved.inherited_brightness=180;
    assert(!dcp_backlight_register(&d) && registered.props.brightness==180);
    assert(dcp_get_brightness(&registered)==180);
    assert(dcp_backlight_controls_device(&registered,NULL));
    return 0;
}
'''
