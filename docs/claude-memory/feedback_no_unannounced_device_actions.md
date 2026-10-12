---
name: feedback_no_unannounced_device_actions
description: "Don't actuate live home devices (AC/lights/etc) for tests without asking first — they affect comfort/WAF"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: e7d16cb9-570e-4eac-9f5d-de2623f1c56a
---

While setting up a "clean baseline" for a test I ran `climate.turn_off` on the central AC without telling the user. They noticed: "something turned the AC off without me touching anything." It affected real comfort.

**Why:** blacky controls the real apartment (AC, fans, boiler). Toggling a device is an outward, comfort-affecting action; doing it silently mid-task is surprising and erodes trust/WAF.

**How to apply:** Before issuing any state-changing service call on a live device (climate/switch/fan/cover) for testing or setup, say what I'm about to do and why, and prefer letting the user drive it or confirm. Read-only/state queries are fine unannounced. If I must change device state, restore it afterward and call that out. Related: [[project_home_automation_arch]].
