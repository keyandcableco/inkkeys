#Notifications on the LED ring, for example from Claude Code hooks.
#
#Other programs report events with the inkkeys-notify script (or by calling notify() below):
#    inkkeys-notify done        a green pulse that fades out (Claude finished)
#    inkkeys-notify attention   amber pulsing until a key on the keyboard is pressed (Claude needs you)
#    inkkeys-notify clear       stops any animation
#Any other event name gives a short white flash.
#
#The event is written to NOTIFY_FILE and the controller picks it up within a fraction of a second.

import math
import os
import sys
import time

NOTIFY_FILE = os.path.join(os.path.expanduser("~"), ".cache", "inkkeys", "notify")

def notify(event):
    os.makedirs(os.path.dirname(NOTIFY_FILE), exist_ok=True)
    tmp = NOTIFY_FILE + ".tmp"
    with open(tmp, "w") as f:
        f.write("%f %s\n" % (time.time(), event))
    os.replace(tmp, NOTIFY_FILE)

def readNotification():
    try:
        with open(NOTIFY_FILE) as f:
            stamp, event = f.read().split(None, 1)
        return float(stamp), event.strip()
    except (OSError, ValueError):
        return None


class Notifier:
    #Animations: color, how long (None = until a key is pressed, at most "limit" seconds), pulses per second
    ANIMATIONS = {
        "done": {"color": (0x00, 0xff, 0x40), "duration": 3.0, "rate": 0.8},
        "attention": {"color": (0xff, 0x90, 0x00), "duration": None, "limit": 120, "rate": 0.6},
    }
    FLASH = {"color": (0x60, 0x60, 0x60), "duration": 0.6, "rate": 1.5} #Never full white: the LEDs share a small power budget

    def __init__(self):
        self.enabled = True
        self.current = None
        self.lastStamp = None
        self.lastCheck = 0
        old = readNotification()
        if old:
            self.lastStamp = old[0] #Events from before the start are not shown

    #Called for every line from the device: any key press dismisses "until a key is pressed" animations
    def onDeviceLine(self, line):
        if self.current and self.current["duration"] is None and len(line) == 2 and line[1] == "p":
            self.current["end"] = True

    def check(self, device):
        now = time.time()
        if now - self.lastCheck < 0.25:
            return
        self.lastCheck = now
        latest = readNotification()
        if not latest or latest[0] == self.lastStamp:
            return
        self.lastStamp = latest[0]
        if not self.enabled or now - latest[0] > 10:
            return
        event = latest[1]
        if event == "clear":
            if self.current:
                self.current["end"] = True
            return
        self.current = dict(self.ANIMATIONS.get(event, self.FLASH), start=now, end=False)

    def animate(self, device):
        self.check(device)
        anim = self.current
        if not anim:
            return
        now = time.time()
        elapsed = now - anim["start"]
        limit = anim["duration"] if anim["duration"] is not None else anim.get("limit", 120)
        if anim["end"] or elapsed > limit:
            self.current = None
            device.ledOverride = False
            device.ledState = None
            device.sendLed(["000000"] * device.nLeds)
            return
        device.ledOverride = True
        #Smooth pulses, fading out over the last second of timed animations
        level = 0.15 + 0.85 * (0.5 - 0.5 * math.cos(2 * math.pi * anim["rate"] * elapsed))
        if anim["duration"] is not None:
            level *= min(1, max(0, anim["duration"] - elapsed))
        r, g, b = (int(c * level) for c in anim["color"])
        device.sendLed(["{:02x}{:02x}{:02x}".format(r, g, b)] * device.nLeds)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: notify.py <done|attention|clear|other>")
        sys.exit(1)
    notify(sys.argv[1])
