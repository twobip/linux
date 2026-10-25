# J616s Type-C DisplayPort handoff

This WIP builds on integration/aurora at
3b77f0f97eb039c00059a7713463ba69eb02af02 and the original three public #451
commits ending at 0012743f982a43c9b345156dd1523e723418c423. It supersedes
wip/j616s-typec-dp-20261026; the replacement is
wip/j616s-typec-dp-20261026-v2 so the published history is preserved without a
force push. #445 and #435 are supplied by integration, not replayed here.
The unchanged public #438 governor dependency fix is also stacked so both
universal configuration profiles retain their requested governor; it still
needs its normal integration review.

#451 supplies the desktop Type-C display fabric and USB3 reclaim groundwork.
The follow-up commits serialize four-lane DP ownership with the USB role,
stop DP link programming before USB can reclaim the block, and retain an
owner if shutdown fails. Desktop display connect runs after every mux provider
has received the assignment. A failed attach is unwound, with a clean failure
allowing USB to continue. appledrm uses the optional-provider handling already
in #446/#451; there is no additional hard dependency on the PHY or crossbar.

The implemented PHY sequence supports four-lane assignments C/E. Assignment D
(two DP lanes plus USB3) is unavailable and leaves USB usable. USB may operate
at USB2 while a C/E assignment reserves all high-speed lanes, even with HPD
low. SuperSpeed returns through the USB role power-on after leaving that
assignment. Two-lane coexistence and controller renegotiation from D to C/E
remain unimplemented: do not count DP plus USB2 as coexistence proof.
USB4/Thunderbolt, retimer operation and peripheral mode remain outside the
implemented T6040 PHY sequences. A failed shutdown retains ownership and can
be retried by later cable events; automatic recovery still needs hardware
proof and review.

The checked-in J616s device tree does not describe the external display
routes. #451 expects loader-enabled dcpext/DART/crossbar resources and
per-port `typec-routes` wiring; its published hardware report used a local
board tree. The obsolete dp-phyN/dp-xbarN dynamic route is gone. Do not test
with guessed firmware-memory mappings. Source DT checks therefore validate
the checked-in board tree, not the absent external display handoff.

## Hardware proof for the m4pro worker

No hardware was accessed by this worker. Confirm the controller's registered
explicit device identity is the intended J616s (M4 Pro/T6040), obtain policy
approval, and retain all session, source, resource and ownership gates on
every hardware request. Keep a known-good rollback kernel and a control path
independent of the port under test. Retain complete boot and failure logs in
private artifacts; publish only sanitized conclusions.

Ryan needs cables in the morning if a monitor and SuperSpeed device are not
already attached. Required: USB-C DP monitor/cable, a known SuperSpeed device,
and preferably a dock that exposes the negotiated pin assignment.

1. With a reviewed board/loader handoff, connect the DP monitor to each port.
   Test cold plug, repeated hotplug/unplug, and both plug orientations. Record
   negotiated pin assignment, lane count, modes, image and disconnect.
2. Measure the USB3 device's negotiated speed before DP, then leave DP alt
   mode, reconnect USB3 and verify the same speed without rebooting. Repeat
   cycles on all ports in both orientations. Keep USB2 available during C/E.
3. Lower HPD without leaving C/E (for example, monitor power off/on through a
   dock). Verify USB3 does not take the reserved lanes and DP returns. A D
   assignment must not claim a working display; USB should still enumerate.
4. Put a second port in DP alt mode without a sink, then connect a display on
   another port. Test two displays competing for the single pipeline and
   unplug the owner. Check that one port cannot disconnect another display.
5. Suspend/resume with DP, USB3 and empty ports, and change the cable asleep.
   Verify display hotplug, SuperSpeed, PD/charging, MagSafe and internal panel
   after resume. Device-only pm_test does not establish s2idle success.
6. Inject DP setup failure and check that USB continues. Inject link-off or
   firmware-disconnect failure and check that ownership is retained, the
   crossbar is not handed elsewhere, and no live USB PIPE is moved. Retain
   failures and rollback evidence. Test recovery after the failure clears.
7. Boot with optional crossbar/PHY display providers unavailable and check
   the internal panel. USB needs its PHY provider; module independence does
   not imply USB operation without that driver.

Hardware proof, two-lane support/renegotiation and the external board handoff
are outstanding. Software gate receipts are retained outside this public
source tree and must name the exact tested commit.
