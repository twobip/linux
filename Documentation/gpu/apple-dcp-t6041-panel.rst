.. SPDX-License-Identifier: GPL-2.0-only OR MIT

T6041 internal panel
===================

Desktop 26.6 firmware uses its own IOMFB instance. Panel brightness is in
integer nits from zero to the panel ceiling, with the same 250 ms fade used
by the H17P panel. The backlight interface reports the requested target and
``actual_brightness`` follows accepted, completed presents. A registration
default does not change the brightness inherited from the boot loader.
Until a loader hint or a completed user request supplies a known level,
``actual_brightness`` reports the target. Echoing the unchanged registration
value also leaves the panel alone while its level is unknown. A request for a
different target takes control. Once a hint or completed request establishes
the level, all targets are usable. Framebuffer unblank and core suspend
notifications also preserve an unknown inherited level.
The first explicit change fades from a known inherited level, or from the
reporting target when no hint is available. Firmware reports are observations,
not requests. After takeover they cannot replace the target, restart a fade or
cause a brightness write. Actual readback follows accepted, completed presents.
Ambient-light policy can use the normal backlight interface, just as a slider
does. Requests made while blanked or suspended preserve the restore target.

Fixed refresh modes keep the timing and color IDs supplied by DCP. The driver
does not synthesize lower refresh modes from a 120 Hz mode. Fractional rates
remain in 16.16 Hz until the DRM pixel clock is calculated. A ProMotion mode
needs desktop presentation deadlines even with adaptive sync disabled.

Adaptive sync is experimental and disabled by default. To qualify the internal
panel, boot with ``appledrm.t6041_vrr=1``. This enables the connector capability
only for the internal main display and a valid adaptive-sync range. The
existing internal ProMotion convention supplies 24 Hz to the mode rate when
the firmware omits both range fields or reports both as zero placeholders;
a partial, duplicate or invalid range
leaves the timing usable at fixed refresh.

A rejected adaptive-sync parameter or mode selection gets one retry with
adaptive sync disabled. An adaptive swap that stops completing invokes the
swap watchdog and re-applies the active CRTC at fixed refresh. Either failure
latches adaptive sync off until reboot. A transport that stops replying cannot
be recovered by issuing another command on its busy channel; it still requires
a reboot. Use the previous kernel entry if a panel fails qualification.

Panel identity
--------------

The desktop internal panel has no external EDID service. Its ProductAttributes
supply the monitor identity, independently of optional colorimetry or timing
fields. The driver publishes an EDID using that product data, the panel dimensions
from the device tree, and a representable DCP timing plus catalog limits.
The EDID clock rounds to its required 10 kHz units. DRM still uses the exact
firmware timing list; the EDID adds no synthetic modes or color capabilities.

Compact powerlog reports may be bare serialized dictionaries or carry a command
descriptor. The receiver preserves the serialization header before handing the
report to systemep. Only the first valid report before Linux control can seed
takeover; later reports confirm output without changing the requested target.

Desktop mode changes use the D202 and D454 adapters for this firmware's records.
The callback table also includes physical mapping and the empty resize
notification. An unknown callback during a modeset gets a bounded unsupported
reply. Its enclosing command must ACK before the set fails, so a subsequent
mode change can reuse the drained channel. Accepted atomic modeset errors are
reported through the out-fence. A timed-out command retains its channel until
the firmware replies; another set cannot overwrite its stack.
