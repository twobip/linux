# SPDX-License-Identifier: GPL-2.0-only OR MIT
# Copyright 2026 Ryan Murray
"""Desktop Type-C finalization and failed-attach ownership, without hardware."""
from common import block


def lifecycle(root):
    source = (root / 'drivers/gpu/drm/apple/dcp-fabric.c').read_text()
    production = '\n'.join(block(source, marker) for marker in (
        'static bool dcp_typec_route_is_dp(',
        'int dcp_typec_phy_on(',
        'static int dcp_typec_route_phy_off(',
        'static int dcp_typec_desktop_release(',
        'static void dcp_typec_port_attach(',
        'static void dcp_typec_route_abort(',
        'static int dcp_typec_route_finish(',
    ))
    return r'''
#include <assert.h>
#include <stdbool.h>
#include <errno.h>
#include <stdio.h>
#define TYPEC_STATE_SAFE 0
#define TYPEC_DP_STATE_A 2
#define TYPEC_DP_STATE_F 7
#define USB_TYPEC_DP_SID 0xff01
#define DP_STATUS_HPD_STATE 1
#define DCP_FIRMWARE_V_26_6_DESKTOP 26
#define READ_ONCE(x) (x)
#define lockdep_assert_held(lock) ((void)(lock))
#define WRITE_ONCE(x, v) ((x) = (v))
#define guard(kind) (void)
#define to_platform_device(dev) (dev)
#define typec_mux_get_drvdata(mux) ((mux)->route)
#define dev_warn(...) ((void)0)
static int dcp_typec_fabric_lock;
struct phy { int unused; };
struct apple_dcp { int fw_compat, hpd_mutex, nr_typec_routes;
 void *dev, *fixed_phy, *typec_connector; bool typec_cable_connected;
 struct apple_dcp_typec_route *active_typec_route; };
struct apple_dcp_typec_route {
 struct apple_dcp *dcp; struct apple_dcp_typec_port *port;
 struct phy *phy; bool phy_powered;
};
struct apple_dcp_typec_port {
 struct apple_dcp_typec_route *owner;
 bool hpd, dp_hpd, dp_wanted, safe_pending, safe_finish_ready, applied_valid;
};
struct typec_mux_dev { struct apple_dcp_typec_route *route; };
struct typec_altmode { unsigned svid; };
struct typec_displayport_data { unsigned status; };
struct typec_mux_state { struct typec_altmode *alt; unsigned long mode; void *data; };
static int power_off_error, disconnect_error, connect_error, exit_calls, disconnect_calls;
static int connect_calls, deselect_calls;
static bool phy_assignment_seen;
static int phy_power_off(struct phy *p) { (void)p; return power_off_error; }
static int phy_exit(struct phy *p) { (void)p; exit_calls++; return 0; }
static int dcp_typec_route_phy_off(struct apple_dcp_typec_route *);
static struct apple_dcp_typec_route *active;
int dcp_typec_phy_on(struct apple_dcp *dcp);
static int dcp_typec_route_phy_on(struct apple_dcp_typec_route *r)
{
 assert(phy_assignment_seen); r->phy_powered=true; return 0;
}
static int dcp_dptx_connect_oob(void *dev, int port)
{
 (void)dev; (void)port; assert(phy_assignment_seen); connect_calls++;
 int ret=dcp_typec_phy_on(active->dcp);
 return ret ?: connect_error;
}
static int dcp_dptx_disconnect_oob(void *dev, int port)
{
 (void)dev; (void)port; disconnect_calls++;
 if (disconnect_error) return disconnect_error;
 return dcp_typec_route_phy_off(active);
}
static int dcp_typec_route_deactivate(struct apple_dcp_typec_route *r)
{
 int ret=dcp_typec_route_phy_off(r);
 if (!ret) deselect_calls++;
 return ret;
}
''' + production + r'''
int main(void)
{
 struct apple_dcp dcp={.fw_compat=DCP_FIRMWARE_V_26_6_DESKTOP};
 struct apple_dcp_typec_port port={0};
 struct apple_dcp_typec_route route={.dcp=&dcp,.port=&port};
 struct typec_mux_dev mux={.route=&route};
 struct typec_altmode alt={.svid=USB_TYPEC_DP_SID};
 struct typec_displayport_data data={.status=DP_STATUS_HPD_STATE};
 struct typec_mux_state state={.alt=&alt,.mode=TYPEC_DP_STATE_A,.data=&data};
 active=&route;
 /* An idle Type-C pointer is for service discovery, never for a link claim. */
 dcp.nr_typec_routes=1;
 assert(dcp_typec_phy_on(&dcp)==-ENOLINK);
 dcp.fixed_phy=&route;
 assert(!dcp_typec_phy_on(&dcp));
 dcp.fixed_phy=NULL;
 dcp.nr_typec_routes=0;
 assert(!dcp_typec_phy_on(&dcp));
 dcp.nr_typec_routes=1;
 dcp.active_typec_route=&route;
 /* A retained route at HPD-low must not admit a racing startup/reconnect. */
 assert(dcp_typec_phy_on(&dcp)==-ENOLINK);
 assert(!route.phy_powered);
 /* Busy is reported after all mode switches can receive their assignment. */
 assert(dcp_typec_route_finish(&mux,&state)==-ENOSPC);
 assert(!connect_calls && !port.owner);
 /* Either provider may set first. Neither set may start a display before end. */
 for (int order=0; order<2; order++) {
  phy_assignment_seen=false; port.owner=NULL; port.hpd=false;
  int before=connect_calls;
  if (order) phy_assignment_seen=true;
  port.owner=&route;
  assert(connect_calls==before);
  phy_assignment_seen=true;
  assert(!dcp_typec_route_finish(&mux,&state));
  assert(port.hpd && port.applied_valid && route.phy_powered);
  assert(!dcp_typec_route_finish(&mux,&state));
  assert(connect_calls==before+1);
  assert(!dcp_typec_desktop_release(&port));
 }
 /* An error in another set provider rolls back the unused route. */
 port.owner=&route; port.hpd=false;
 dcp_typec_route_abort(&mux,&state);
 assert(!port.owner && !route.phy_powered);
 /* A request-display failure is cleaned up and USB gets an unavailable result. */
 port.owner=&route; connect_error=-EIO;
 assert(dcp_typec_route_finish(&mux,&state)==-ENODEV);
 assert(!port.owner && !dcp.typec_cable_connected && !route.phy_powered);
 /* A waiting sink which fails attach is cleaned up, not published as live. */
 port.owner=&route; port.dp_hpd=true; port.dp_wanted=true;
 dcp.typec_connector=&port;
 dcp_typec_port_attach(&port);
 assert(!port.owner && !port.hpd && !port.dp_wanted && !port.dp_hpd);
 /* Failed power-off must not exit the PHY, deselect or discard its owner. */
 port.owner=&route; route.phy_powered=true; power_off_error=-ETIMEDOUT;
 int exits=exit_calls, deselects=deselect_calls;
 assert(dcp_typec_route_finish(&mux,&state)==-ETIMEDOUT);
 assert(port.owner==&route && route.phy_powered);
 assert(exit_calls==exits && deselect_calls==deselects);
 dcp_typec_route_abort(&mux,&state);
 assert(port.owner==&route && route.phy_powered);
 power_off_error=0; connect_error=0;
 assert(!dcp_typec_desktop_release(&port));
 /* Firmware stop failure also retains the PHY and crossbar. */
 port.owner=&route; route.phy_powered=true; disconnect_error=-EIO;
 assert(dcp_typec_desktop_release(&port)==-EIO);
 assert(port.owner==&route && route.phy_powered);
 disconnect_error=0;
 assert(!dcp_typec_desktop_release(&port));
 /* SAFE finalization only publishes readiness after successful stop. */
 port.owner=&route; port.safe_pending=true; route.phy_powered=true;
 state.mode=TYPEC_STATE_SAFE; state.alt=NULL; power_off_error=-ETIMEDOUT;
 assert(dcp_typec_route_finish(&mux,&state)==-ETIMEDOUT);
 assert(!port.safe_finish_ready && port.owner==&route);
 power_off_error=0;
 assert(!dcp_typec_route_finish(&mux,&state));
 assert(port.safe_finish_ready && port.owner==&route);
 assert(disconnect_calls>0);
 puts("desktop Type-C finalization and failure ownership: PASS");
 return 0;
}
'''


def startup(root):
    source = (root / 'drivers/gpu/drm/apple/dcp.c').read_text()
    production = block(source, 'static int dcp_start_desktop_external(')
    return r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <errno.h>
typedef uint32_t u32;
#define IS_ENABLED(x) 0
#define BIT(n) (1U << (n))
#define dev_warn(...) ((void)0)
#define dev_info(...) ((void)0)
#define dev_err_probe(dev, ret, ...) (ret)
enum { DPDEV_ENDPOINT=0x20, DPAV_CTRL_ENDPOINT, DPSAC_ENDPOINT, AV_ENDPOINT,
 REMOTE_ALLOC_ENDPOINT, EPIC2C_ENDPOINT, DCP_EXPERT_ENDPOINT, EPIC25_ENDPOINT };
struct dcp_desktop_state { unsigned graph_started; };
struct dptx_port { bool available; };
struct apple_dcp {
 struct dcp_desktop_state *desktop; void *dev, *phy; unsigned nr_typec_routes;
 struct dptx_port dptxport[1];
};
static bool unstable_edid;
static unsigned dptx_starts, connect_attempts;
static int dcp_desktop_start_ext_ep(struct apple_dcp *d, u32 map, unsigned ep, const char *name)
{ (void)d; (void)map; (void)ep; (void)name; return 0; }
static int dcp_desktop_start_dpavctrl(struct apple_dcp *d) { (void)d; return 0; }
static int ibootep_init(struct apple_dcp *d) { (void)d; return 0; }
static int dptxep_init_desktop(struct apple_dcp *d, unsigned ep)
{ (void)ep; dptx_starts++; d->dptxport[0].available=true; return 0; }
static int dpavservep_init(struct apple_dcp *d) { (void)d; return 0; }
static bool dptx_service_available(struct dptx_port *p) { return p->available; }
static int dcp_dptx_connect(struct apple_dcp *d, unsigned port)
{
 (void)port; connect_attempts++;
 /* The separately tested admission wrapper refuses an unclaimed Type-C link. */
 return d->phy ? 0 : -ENOLINK;
}
''' + production + r'''
int main(void)
{
 struct dcp_desktop_state desktop={0};
 struct apple_dcp dcp={.desktop=&desktop};
 assert(!dcp_start_desktop_external(&dcp,0));
 assert(!dptx_starts && !connect_attempts);
 /* Route release parks ->phy at NULL. A later restart must discover DPTX. */
 dcp.nr_typec_routes=3;
 assert(!dcp_start_desktop_external(&dcp,0));
 assert(dptx_starts==1 && connect_attempts==1 && dcp.dptxport[0].available);
 /* Fixed HDMI still takes its existing startup path. */
 dcp.nr_typec_routes=0; dcp.phy=&desktop;
 assert(!dcp_start_desktop_external(&dcp,0));
 assert(dptx_starts==2 && connect_attempts==2);
 return 0;
}
'''
