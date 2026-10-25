.. SPDX-License-Identifier: GPL-2.0-only OR MIT

T6041 internal panel
===================

Desktop 26.6 firmware uses its own IOMFB instance. Panel brightness is in
integer nits from zero to the panel ceiling, with the same 250 ms fade used
by the H17P panel. The backlight interface reports the requested target and
``actual_brightness`` follows accepted, completed presents. A registration
default does not change the brightness inherited from the boot loader.
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
the firmware omits both range fields; an explicit partial or invalid range
leaves the timing usable at fixed refresh.

A rejected adaptive-sync parameter or mode selection gets one retry with
adaptive sync disabled. An adaptive swap that stops completing invokes the
swap watchdog and re-applies the active CRTC at fixed refresh. Either failure
latches adaptive sync off until reboot. A transport that stops replying cannot
be recovered by issuing another command on its busy channel; it still requires
a reboot. Use the previous kernel entry if a panel fails qualification.
