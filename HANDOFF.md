# J616s Type-C DisplayPort work

This branch combines the public T6041 display series with its crossbar and
power-domain dependencies. The changes keep appledrm independent of optional
PHY and crossbar modules and serialize USB3 versus four-lane DP ownership.
Software checks do not prove board behaviour. No hardware was accessed for
this work.

The T6040 PHY supports four-lane assignments C/E. Assignment D is rejected
without reporting a working display, and USB remains available. Two-lane DP
plus USB3 needs a verified T6040 programming sequence before it can be enabled.
USB4, Thunderbolt and peripheral mode are still unsupported by this PHY.
Automatic renegotiation from D to C/E is not implemented.

Full Neo parity remains incomplete. The desktop T6041 path still uses the
shared out-of-band connector model rather than the complete Type-C fabric.
Multi-port isolation needs that integration and hardware proof. Failed DP
shutdown retains ownership; bounded automatic drain/retry beyond later cable
events also needs further work before merge.

The source device tree does not yet describe J616s external display routes.
The display series expects loader-enabled dcpext nodes, DART mappings,
crossbars and the per-port dp-phyN/dp-xbarN wiring. The kernel changes alone do
not provide that handoff. Do not test with guessed firmware-memory mappings.

## Hardware checks

The hardware worker must confirm the controller's registered device ID is
this J616s, M4 Pro/T6040, and use that explicit ID on every request with policy
approval and the usual session, source, resource and ownership gates.
Keep complete logs for every boot and preserve a known-good rollback kernel.
Keep a control path available that does not depend on the port under test.
Do not publish raw logs or machine identifiers.

These checks need cables if no monitor or USB3 device is attached:

1. Connect a USB-C DP monitor to each port in turn. Confirm hotplug, modeset,
   image and disconnect, then repeat with the plug flipped. Test both cold
   plug and hotplug. Record the negotiated pin assignment and lane count.
2. Measure a known SuperSpeed device's negotiated speed before the DP session.
   Disconnect DP, reconnect that device and confirm the same speed without
   rebooting. Repeat several cycles in both orientations on each port.
3. With a four-lane DP dock, USB2 may remain available while DP uses all four
   high-speed lanes. After leaving DP alt mode, SuperSpeed must return. Assignment D
   must not claim a display on this driver. USB should still enumerate.
4. Suspend and resume with DP attached, with USB3 attached, and with empty
   ports. Also change the cable while asleep. Check hotplug and SuperSpeed
   after resume, PD/charging and MagSafe, and the internal panel.
5. With display routing unavailable or DP setup failing, the internal panel
   and USB must remain usable. With the entire Type-C PHY module absent,
   check that the internal panel still works; USB needs its PHY provider.
   A failed DP shutdown must retain the route and avoid moving a live PIPE.

A combined DP+USB3 two-lane test remains pending driver support. Do not count
four-lane DP with USB2 as evidence of two-lane coexistence.
