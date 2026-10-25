# SPDX-License-Identifier: GPL-2.0-only OR MIT
# Copyright 2026 Ryan Murray
"""Desktop Type-C finalization and failed-attach ownership, without hardware."""
from common import block


def lifecycle(root):
    source = (root / 'drivers/gpu/drm/apple/dcp-fabric.c').read_text()
    production = '\n'.join(block(source, marker) for marker in (
        'static bool dcp_typec_route_is_dp(',
        'static int dcp_typec_route_phy_off(',
        'static int dcp_typec_desktop_release(',
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
#define WRITE_ONCE(x, v) ((x) = (v))
#define guard(kind) (void)
#define to_platform_device(dev) (dev)
#define typec_mux_get_drvdata(mux) ((mux)->route)
#define dev_warn(...) ((void)0)
static int dcp_typec_fabric_lock;
struct phy { int unused; };
struct apple_dcp { int fw_compat; void *dev; bool typec_cable_connected; };
struct apple_dcp_typec_route {
 struct apple_dcp *dcp; struct apple_dcp_typec_port *port;
 struct phy *phy; bool phy_powered;
};
struct apple_dcp_typec_port {
 struct apple_dcp_typec_route *owner;
 bool hpd, safe_pending, safe_finish_ready, applied_valid;
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
static int dcp_dptx_connect_oob(void *dev, int port)
{
 (void)dev; (void)port; assert(phy_assignment_seen); connect_calls++;
 active->phy_powered=true; return connect_error;
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
