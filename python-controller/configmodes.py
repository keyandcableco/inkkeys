#Modes defined in layouts.json instead of Python code. The configurator (configurator.py)
#edits that file and the controller reloads it automatically when it changes.
#
#A mode in layouts.json looks like this:
#
#  {"name": "Chrome", "enabled": true,
#   "match": {"type": "window", "pattern": "chrome"},      (or "always", or {"type": "process", "name": "obs"})
#   "title": "Chrome",
#   "buttons": {"2": {"display": {"icon": "icons/plus-square.png"},
#                     "action": {"type": "keys", "keys": ["KEY_LEFT_CTRL", "KEY_T"]}}, ...},
#   "jog": [{"label": "Mouse Wheel", "cw": {"type": "wheel", "amount": -2}, "ccw": {"type": "wheel", "amount": 2}}, ...],
#   "jogPress": {...action...}}                             (only used if there are less than two jog functions)
#
#Instead of buttons and jog functions, a mode can name a class from modes.py with "python": "ModeOBS"
#for behavior that needs code (OBS control, polling, animations...).

import json
import os
import re
import subprocess
import sys
import time
import zlib
from inkkeys import *
from inkkeys.device import BASE_DIR, resolvePath

CONFIG_FILE = os.path.join(BASE_DIR, "layouts.json")

#While the configurator is open, it writes the mode being edited (including unsaved changes) to
#this file and touches it every few seconds. The controller shows that mode until the file goes stale.
PREVIEW_FILE = os.path.join(BASE_DIR, ".preview.json")
PREVIEW_TIMEOUT = 6

def readPreview():
    try:
        if time.time() - os.path.getmtime(PREVIEW_FILE) > PREVIEW_TIMEOUT:
            return None
        with open(PREVIEW_FILE) as f:
            return json.load(f).get("mode")
    except (OSError, ValueError):
        return None

N_EVENTS = 10 #Maximum number of events per key in the firmware (N_EVENTS in eventsequence.h)

BUTTONS = [2, 3, 4, 5, 6, 7, 8, 9]

#Action types. Buttons hold keys while pressed, the jog dial taps them once per step.
ACTION_TYPES = {
    "none": "Nothing",
    "keys": "Key combination",
    "media": "Media key",
    "mouse": "Mouse button",
    "wheel": "Mouse wheel",
    "mouse_x": "Move mouse horizontally",
    "mouse_y": "Move mouse vertically",
    "raw": "Custom event sequence",
    "text": "Type text",
    "open": "Open a website or file",
    "command": "Run a command",
}
#Actions the controller performs itself, the keyboard cannot store them
CONTROLLER_TYPES = ("text", "open", "command")

#Defaults for the "settings" section of layouts.json
DEFAULT_SETTINGS = {
    "fullRefreshEvery": 20,  #Mode switches between full refreshes, 0 = never
    "longPressMs": 450,      #How long a key must be held for its "hold" action
    "doubleTapMs": 300,      #How quickly the second tap of a double tap must follow
    "notifications": True,   #Light up the LEDs for notifications (see notify.py)
    "standalone": None,      #Name of the mode saved on the keyboard for use without the controller
    "comboHints": True,      #While a key with combos is held, show the combos on the screen
    "comboHintMs": 350,      #...once it has been held this long
}

#What the screen shows for a combo while its key is held: (label, small text)
def hintText(action):
    t = action.get("type")
    label = action.get("label")
    if not label:
        if t == "text":
            label = action.get("text", "").strip().split("\n")[0]
        else:
            label = describeAction(action)
    kind = {"text": "types", "open": "opens", "command": "runs"}.get(t, "")
    return label, kind

def setting(settings, name):
    value = (settings or {}).get(name)
    return DEFAULT_SETTINGS.get(name) if value is None else value

AXES = {"wheel": MouseAxisCode.MOUSE_WHEEL, "mouse_x": MouseAxisCode.MOUSE_X, "mouse_y": MouseAxisCode.MOUSE_Y}


# ==================== Loading and saving ====================

def loadConfig(path=CONFIG_FILE):
    with open(path) as f:
        return json.load(f)

def saveConfig(config, path=CONFIG_FILE):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
    os.replace(tmp, path) #Atomic, so the controller never reads a half-written file


# ==================== Actions to event sequences ====================

def _keyEvents(keys, action):
    return [event(DeviceCode.KEYBOARD, KeyboardKeycode[k], action) for k in keys]

#Returns (press, release) event lists for a button
def buttonEvents(action):
    t = (action or {}).get("type", "none")
    if t == "keys" and action.get("tap"):
        return jogEvents(action), []  #Pressed and released right away when the button goes down
    if t == "keys":
        keys = action.get("keys", [])
        return _keyEvents(keys, ActionCode.PRESS), _keyEvents(reversed(keys), ActionCode.RELEASE)
    if t == "media":
        key = ConsumerKeycode[action["key"]]
        return [event(DeviceCode.CONSUMER, key, ActionCode.PRESS)], [event(DeviceCode.CONSUMER, key, ActionCode.RELEASE)]
    if t == "mouse":
        button = MouseKeycode[action["button"]]
        return [event(DeviceCode.MOUSE, button, ActionCode.PRESS)], [event(DeviceCode.MOUSE, button, ActionCode.RELEASE)]
    if t in AXES:
        return [event(DeviceCode.MOUSE, AXES[t], int(action.get("amount", 1)))], []
    if t == "raw":
        return list(action.get("press", [])), list(action.get("release", []))
    return [], []

#Actions that need the controller, because the firmware cannot store them on a key
def needsController(action):
    return (action or {}).get("type") in CONTROLLER_TYPES

#Opens a website or file with the default program, or runs a shell command, without waiting for it
def launch(action):
    t = action.get("type")
    try:
        if t == "open":
            subprocess.Popen(["xdg-open", action.get("target", "")], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        elif t == "command":
            subprocess.Popen(action.get("command", ""), shell=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as e:
        print("Could not run " + str(action) + ": " + str(e))

def isSet(action):
    if not action or action.get("type", "none") == "none":
        return False
    if action["type"] == "keys":
        return bool(action.get("keys"))
    if action["type"] == "text":
        return bool(action.get("text"))
    if action["type"] == "open":
        return bool(action.get("target"))
    if action["type"] == "command":
        return bool(action.get("command"))
    return True

#Events that perform an action once, pressing and releasing right away (used for gestures)
def tapEvents(action):
    if (action or {}).get("type") == "raw" and "events" not in action:
        return list(action.get("press", [])) + list(action.get("release", []))
    return jogEvents(action)

#Returns the event list for one step of the jog dial
def jogEvents(action):
    t = (action or {}).get("type", "none")
    if t == "keys":
        #Hold the modifiers, stroke the last key (press+release in one event), release the modifiers
        keys = action.get("keys", [])
        if not keys:
            return []
        return _keyEvents(keys[:-1], ActionCode.PRESS) + [event(DeviceCode.KEYBOARD, KeyboardKeycode[keys[-1]])] + _keyEvents(reversed(keys[:-1]), ActionCode.RELEASE)
    if t == "media":
        return [event(DeviceCode.CONSUMER, ConsumerKeycode[action["key"]])]
    if t == "mouse":
        return [event(DeviceCode.MOUSE, MouseKeycode[action["button"]])]
    if t in AXES:
        return [event(DeviceCode.MOUSE, AXES[t], int(action.get("amount", 1)))]
    if t == "raw":
        return list(action.get("events", []))
    return []

#Checks an action and returns a list of problems (empty if it is fine)
def validateAction(action, jog=False, limit=True):
    problems = []
    if (action or {}).get("type") in ("open", "command"):
        return [] if isSet(action) else ["Nothing to open or run yet."]
    if (action or {}).get("type") == "text":
        if any(ord(c) > 126 or (ord(c) < 32 and c != "\n") for c in action.get("text", "")):
            problems.append("Only plain ASCII characters can be typed, others are skipped.")
        return problems
    try:
        if jog:
            n = len(jogEvents(action))
        else:
            press, release = buttonEvents(action)
            n = max(len(press), len(release))
    except (KeyError, ValueError) as e:
        return ["Unknown key or value: " + str(e)]
    if limit and n > N_EVENTS:
        problems.append("Needs " + str(n) + " events, the device stores at most " + str(N_EVENTS) + (" (a jog step presses and releases each key, so at most 5 keys)" if jog else ""))
    return problems

KEY_LABELS = {"KEY_LEFT_CTRL": "Ctrl", "KEY_RIGHT_CTRL": "RCtrl", "KEY_LEFT_SHIFT": "Shift", "KEY_RIGHT_SHIFT": "RShift",
              "KEY_LEFT_ALT": "Alt", "KEY_RIGHT_ALT": "AltGr", "KEY_LEFT_WINDOWS": "Super", "KEY_RIGHT_WINDOWS": "RSuper",
              "KEY_LEFT_GUI": "Super", "KEY_RIGHT_GUI": "RSuper", "KEY_PAGE_UP": "PgUp", "KEY_PAGE_DOWN": "PgDn",
              "KEY_ESC": "Esc", "KEY_ENTER": "Enter", "KEY_RETURN": "Enter"}

def keyLabel(name):
    if name in KEY_LABELS:
        return KEY_LABELS[name]
    for prefix in ("KEY_", "MEDIA_", "CONSUMER_"):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return name.replace("_", " ").title() if len(name) > 1 else name

#A short human readable description of an action, used in the configurator
def describeAction(action):
    t = (action or {}).get("type", "none")
    if t != "none" and (action or {}).get("label"):
        return action["label"] #Named by the user (combos, launchers)
    if t == "keys":
        return ("+".join(keyLabel(k) for k in action.get("keys", [])) or "Nothing") + (" (tap)" if action.get("tap") else "")
    if t == "media":
        return keyLabel(action.get("key", ""))
    if t == "mouse":
        return {"MOUSE_LEFT": "Left click", "MOUSE_RIGHT": "Right click", "MOUSE_MIDDLE": "Middle click", "MOUSE_PREV": "Back button", "MOUSE_NEXT": "Forward button"}.get(action.get("button"), action.get("button", ""))
    if t in AXES:
        return ACTION_TYPES[t] + " " + "{:+d}".format(int(action.get("amount", 1)))
    if t == "open":
        target = action.get("label") or re.sub(r"^https?://", "", action.get("target", "")).rstrip("/")
        return "Open " + (target[:24] + "\u2026" if len(target) > 24 else target)
    if t == "command":
        if action.get("label"):
            return action["label"]
        command = action.get("command", "")
        return "Run " + (command[:22] + "\u2026" if len(command) > 22 else command)
    if t == "text":
        text = action.get("text", "")
        return "Type \u201c" + (text[:18] + "\u2026" if len(text) > 18 else text).replace("\n", "\u21b5") + "\u201d"
    if t == "raw":
        if "events" in action:
            return describeEvents(action["events"])
        press, release = describeEvents(action.get("press", [])), describeEvents(action.get("release", []))
        return press if not action.get("release") else press + " / " + release
    return "Nothing"

#Readable form of raw device events, e.g. ["k79", "d20", "k40"] -> "Right Arrow, Enter"
def describeEvents(events):
    parts = []
    for e in events:
        p = _parseEvent(e)
        try:
            if e.startswith("d") and e[1:].isdigit():
                continue #Short pauses are an implementation detail
            elif p and p[0] == "k":
                parts.append(keyLabel(KeyboardKeycode(int(p[1])).name) + {"p": " down", "r": " up"}.get(p[2], ""))
            elif p and p[0] == "c":
                parts.append(keyLabel(ConsumerKeycode(int(p[1])).name) + {"p": " down", "r": " up"}.get(p[2], ""))
            else:
                parts.append(e)
        except ValueError:
            parts.append(e)
    return ", ".join(parts) or "Nothing"


# ==================== Volume display on the LED ring ====================

def getVolume():
    try:
        out = subprocess.run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"], capture_output=True, text=True, timeout=1).stdout
        values = [int(v) for v in re.findall(r"(\d+)%", out)]
        return sum(values) / len(values) / 100 if values else None
    except (OSError, subprocess.SubprocessError):
        return None

def parseColor(c):
    return int(str(c).lstrip("#"), 16)


# ==================== The mode ====================

#Everything a key can do: "tap", "long" (held), "double" (tapped twice) and "combos"
#({other key: action} for holding this key and pressing the other one). Key 1 is pressing the dial.
def gesturesFor(spec, key):
    if key == 1:
        g = spec.get("dialGestures") or {}
        tap = spec.get("jogPress")
    else:
        g = (spec.get("buttons") or {}).get(str(key)) or {}
        tap = g.get("action")
    combos = {}
    for other, action in (g.get("combos") or {}).items():
        if isSet(action) and str(other).isdigit() and 1 <= int(other) <= 9 and int(other) != key:
            combos[int(other)] = action
    return {"tap": tap, "long": g.get("long") if isSet(g.get("long")) else None,
            "double": g.get("double") if isSet(g.get("double")) else None, "combos": combos}

def accelerates(function):
    if function.get("accelerate") is not None:
        return bool(function["accelerate"])
    return (function.get("cw") or {}).get("type") in AXES #Scrolling and mouse movement speed up by default

def keyCode(key, pressed):
    return KeyCode["SW" + str(key) + ("_PRESS" if pressed else "_RELEASE")]


class ConfigMode:
    def __init__(self, spec, settings=None):
        self.spec = spec
        self.settings = settings or {}
        self.jogIndex = 0
        self.held = {}         #Key -> state while it is down
        self.pendingTaps = {}  #Key -> time of a tap that may become a double tap
        self.hintFor = None    #Key whose combos are shown on the screen

    def showTile(self, device, n, display):
        display = display or {}
        if display.get("icon"):
            device.sendIconFor(n, display["icon"], inverted=display.get("inverted", False), centered=display.get("centered", True),
                               marked=display.get("marked", False), crossed=display.get("crossed", False))
        else:
            device.sendTextFor(n, display.get("text", ""), display.get("subtext", ""), inverted=display.get("inverted", False))

    def activate(self, device):
        spec = self.spec
        self.held, self.pendingTaps, self.hintFor = {}, {}, None
        self.cycles = len(spec.get("jog", [])) > 1  #Pressing the dial selects the next function
        self.gestures = {k: gesturesFor(spec, k) for k in range(1, 10)}
        if device.version < 2:
            #Older firmware cannot run events on request, so only plain taps work
            for g in self.gestures.values():
                g.update(long=None, double=None, combos={})
        g = self.gestures
        partners = {other for k in g for other in g[k]["combos"]}
        #Keys whose tap has to wait for the release, to tell it apart from holding, double tapping or a combo
        self.deferred = {k for k in g if g[k]["long"] or g[k]["double"] or g[k]["combos"]}
        if self.cycles:
            self.deferred.add(1)
        #Keys the controller handles, the firmware gets no assignment for them
        self.handled = set(self.deferred) | partners
        if device.version >= 2:
            self.handled |= {k for k in g if needsController(g[k]["tap"])}

        device.sendTextFor("title", spec.get("title", spec.get("name", "")), inverted=True)
        buttons = spec.get("buttons", {})
        for n in BUTTONS:
            self.showTile(device, n, buttons.get(str(n), {}).get("display"))
        for k in range(1, 10):
            if k in self.handled:
                device.assignKey(keyCode(k, True), [])
                device.assignKey(keyCode(k, False), [])
                device.registerCallback(lambda k=k: self.onPress(device, k), keyCode(k, True))
                device.registerCallback(lambda k=k: self.onRelease(device, k), keyCode(k, False))
            else:
                press, release = buttonEvents(g[k]["tap"])
                device.assignKey(keyCode(k, True), press[:N_EVENTS])
                device.assignKey(keyCode(k, False), release[:N_EVENTS])
        device.registerCallback(lambda steps: self.onTurn(device, steps), KeyCode.JOG)
        self.selectJog(device, 0, update=False, flash=False)
        device.updateDisplay()

    def selectJog(self, device, index, update=True, flash=True):
        jog = self.spec.get("jog", [])
        function = {}
        if not jog:
            device.sendTextFor(1, "")
        else:
            self.jogIndex = index % len(jog)
            function = jog[self.jogIndex]
            device.sendTextFor(1, function.get("label", ""))
            if flash and function.get("flash") and device.nLeds:
                device.setLeds([parseColor(function["flash"])] * device.nLeds)
        device.assignKey(KeyCode.JOG_CW, jogEvents(function.get("cw"))[:N_EVENTS])
        device.assignKey(KeyCode.JOG_CCW, jogEvents(function.get("ccw"))[:N_EVENTS])
        if device.version >= 2:
            #Turning while the dial is pressed, and speeding up fast turns
            device.assignKey(KeyCode.JOG_PRESSED_CW, jogEvents(function.get("pressCw"))[:N_EVENTS])
            device.assignKey(KeyCode.JOG_PRESSED_CCW, jogEvents(function.get("pressCcw"))[:N_EVENTS])
            device.setOption("A", 1 if function and accelerates(function) else 0)
        if update:
            device.updateDisplay()

    #Runs an action once, through the controller
    def run(self, device, action):
        if (action or {}).get("type") in ("open", "command"):
            launch(action)
        elif (action or {}).get("type") == "text":
            device.typeText(action.get("text", ""))
        elif isSet(action):
            device.execute(tapEvents(action))

    def tap(self, device, k):
        if k == 1 and self.cycles:
            self.selectJog(device, self.jogIndex + 1)
        else:
            self.run(device, self.gestures[k]["tap"])

    def onPress(self, device, k):
        now = time.time()
        #A key pressed while another one is held can be a combo
        for holder in reversed(list(self.held)):
            combo = self.gestures[holder]["combos"].get(k)
            if combo and not self.held[holder].get("consumed"):
                self.held[holder]["comboUsed"] = True
                self.held[k] = {"time": now, "consumed": True}
                self.run(device, combo)
                return
        self.held[k] = {"time": now, "comboUsed": False, "longFired": False, "turned": False, "consumed": False}
        if k not in self.deferred:
            tap = self.gestures[k]["tap"]
            if needsController(tap):
                self.run(device, tap)
            else:
                device.execute(buttonEvents(tap)[0]) #Press now, release on release, like the firmware does

    def onRelease(self, device, k):
        if self.hintFor == k:
            self.hideComboHints(device)
        state = self.held.pop(k, None)
        if state is None or state["consumed"]:
            return
        g = self.gestures[k]
        if k not in self.deferred:
            if not needsController(g["tap"]):
                device.execute(buttonEvents(g["tap"])[1])
            return
        if state["comboUsed"] or state["longFired"] or state["turned"]:
            return
        if g["double"]:
            if self.pendingTaps.pop(k, None) is not None:
                self.run(device, g["double"])
            else:
                self.pendingTaps[k] = time.time() #Wait whether a second tap follows, see animate()
            return
        self.tap(device, k)

    def onTurn(self, device, steps):
        if 1 in self.held:
            self.held[1]["turned"] = True #Turning while pressed is not a press of the dial
        jog = self.spec.get("jog", [])
        if jog and jog[self.jogIndex % len(jog)].get("show") == "volume":
            self.showVolume(device)

    def showVolume(self, device):
        volume = getVolume()
        if volume is None or not device.nLeds:
            return
        device.setLeds([0xff0000 if volume > i/(device.nLeds-1) else 0x00ff00 for i in range(device.nLeds)])

    def poll(self, device):
        return False

    def animate(self, device):
        now = time.time()
        longPress = setting(self.settings, "longPressMs") / 1000
        for k, state in list(self.held.items()):
            if state["consumed"] or state["longFired"] or state["comboUsed"] or state["turned"]:
                continue
            if k in self.deferred and self.gestures[k]["long"] and now - state["time"] >= longPress:
                state["longFired"] = True
                self.pendingTaps.pop(k, None)
                self.run(device, self.gestures[k]["long"])
        if setting(self.settings, "comboHints") and self.hintFor is None:
            delay = setting(self.settings, "comboHintMs") / 1000
            for k, state in list(self.held.items()):
                g = self.gestures[k]
                if g["combos"] and not g["long"] and not state["consumed"] and not state["turned"] and now - state["time"] >= delay:
                    self.showComboHints(device, k)
                    break
        doubleTap = setting(self.settings, "doubleTapMs") / 1000
        for k, t in list(self.pendingTaps.items()):
            if now - t >= doubleTap:
                del self.pendingTaps[k]
                self.tap(device, k)
        device.fadeLeds()

    #Shows on the screen what pressing each key does while key k is held (k = 1 for the dial)
    def showComboHints(self, device, k):
        self.hintFor = k
        combos = self.gestures[k]["combos"]
        device.sendTextFor("title", "HOLDING " + ("DIAL" if k == 1 else "KEY " + str(k)), inverted=True)
        for n in BUTTONS:
            action = combos.get(n)
            if n == k:
                device.sendTextFor(n, "held", inverted=True)
            elif action and action.get("icon"):
                device.sendIconFor(n, action["icon"])
            elif action:
                label, kind = hintText(action)
                device.sendTextFor(n, label, kind)
            else:
                device.sendTextFor(n, "")
        device.sendTextFor(1, ("Press dial: " + hintText(combos[1])[0]) if 1 in combos else "")
        device.updateDisplay()

    def hideComboHints(self, device):
        self.hintFor = None
        spec = self.spec
        device.sendTextFor("title", spec.get("title", spec.get("name", "")), inverted=True)
        for n in BUTTONS:
            self.showTile(device, n, (spec.get("buttons") or {}).get(str(n), {}).get("display"))
        jog = spec.get("jog", [])
        device.sendTextFor(1, jog[self.jogIndex % len(jog)].get("label", "") if jog else "")
        device.updateDisplay()

    def deactivate(self, device):
        #Release what the controller pressed for keys that are still down, nothing may stay stuck
        for k, state in list(self.held.items()):
            if not state["consumed"] and k not in self.deferred and not needsController(self.gestures[k]["tap"]):
                device.execute(buttonEvents(self.gestures[k]["tap"])[1])
        self.held, self.pendingTaps, self.hintFor = {}, {}, None
        device.clearCallbacks()
        if device.version >= 2:
            #Modes in modes.py know nothing about these
            device.assignKey(KeyCode.JOG_PRESSED_CW, [])
            device.assignKey(KeyCode.JOG_PRESSED_CCW, [])
            device.setOption("A", 0)


#Layout saved on the keyboard for use without the controller. Only what the firmware can do on its
#own is saved: the taps of the keys, the first dial function and its press-and-turn.
def fitLabel(text, width, lines):
    text = "".join(c for c in str(text).upper() if 32 <= ord(c) < 127 and c != "|")
    parts = []
    for word in text.split():
        pieces = re.findall(r"[^+]+\+?|\+", word) if len(word) > width else [word]
        parts += [(p, i > 0) for i, p in enumerate(pieces)] #(piece, continues the previous word)
    result = []
    for piece, glued in parts:
        while len(piece) > width:
            result.append(piece[:width])
            piece = piece[width:]
        if result and len(result[-1]) + (0 if glued else 1) + len(piece) <= width:
            result[-1] += ("" if glued else " ") + piece
        else:
            result.append(piece)
    return "|".join(result[:lines])

def standaloneLayout(spec):
    slots = {}
    for n in BUTTONS:
        press, release = buttonEvents(gesturesFor(spec, n)["tap"])
        slots[str(n) + "p"], slots[str(n) + "r"] = press[:N_EVENTS], release[:N_EVENTS]
    jog = spec.get("jog", [])
    press, release = buttonEvents(spec.get("jogPress")) if len(jog) < 2 else ([], [])
    slots["1p"], slots["1r"] = press[:N_EVENTS], release[:N_EVENTS]
    first = jog[0] if jog else {}
    for slot, field in (("R+", "cw"), ("R-", "ccw"), ("P+", "pressCw"), ("P-", "pressCcw")):
        slots[slot] = jogEvents(first.get(field))[:N_EVENTS]
    labels = [fitLabel(spec.get("title", spec.get("name", "")), 16, 1), fitLabel(first.get("label", ""), 16, 1)]
    for n in BUTTONS:
        button = (spec.get("buttons") or {}).get(str(n)) or {}
        display = button.get("display") or {}
        if button.get("label"):
            text = button["label"]
        elif display.get("text"):
            text = display["text"] + " " + display.get("subtext", "").replace("\n", " ")
        elif needsController(button.get("action")):
            text = ""
        else:
            text = describeAction(button.get("action")) if isSet(button.get("action")) else ""
        labels.append(fitLabel(text, 8, 3))
    checksum = (zlib.crc32(json.dumps({"slots": slots, "labels": labels}, sort_keys=True).encode()) & 0x7fffffff) or 1
    return slots, labels, checksum


#Builds the list used by the controller: [{"mode": ..., "matches": function(processes, window)}, ...]
def buildModes(config, pythonModes=None):
    result = []
    for spec in config.get("modes", []):
        if not spec.get("enabled", True):
            continue
        if spec.get("python"):
            cls = getattr(pythonModes, spec["python"], None) if pythonModes else None
            if cls is None:
                print("Mode \"" + spec.get("name", "") + "\": there is no class " + spec["python"] + " in modes.py, skipping it.")
                continue
            try:
                mode = cls()
            except Exception as e:
                print("Mode \"" + spec.get("name", "") + "\" could not be created: " + str(e))
                continue
        else:
            mode = ConfigMode(spec, config.get("settings"))
        result.append({"mode": mode, "name": spec.get("name", ""), "matches": matcher(spec.get("match"))})
    return result

def matcher(match):
    match = match or {"type": "always"}
    t = match.get("type", "always")
    if t == "window":
        regex = re.compile(match.get("pattern", ""), re.IGNORECASE)
        return lambda processes, window: window is not None and regex.search(window) is not None
    if t == "process":
        name = match.get("name", "")
        return lambda processes, window: name in processes
    return lambda processes, window: True


# ==================== Import from modes.py ====================

#A stand-in for the device that records what a Python mode sets up, so existing
#modes can be converted into layouts.json entries.
class RecordingDevice(Device):
    def __init__(self):
        super().__init__()
        self.nLeds = 12
        self.tiles = {}
        self.keys = {}
        self.ledsSet = None

    def sendToDevice(self, command):
        pass

    def sendBinaryToDevice(self, data):
        pass

    def updateDisplay(self, fullRefresh=False, timeout=6):
        return True

    def sendTextFor(self, function, text, subtext="", inverted=False):
        self.tiles[function] = {"text": text, "subtext": subtext, "inverted": inverted}

    def sendIconFor(self, function, icon, inverted=False, centered=True, marked=False, crossed=False):
        self.tiles[function] = {"icon": icon, "inverted": inverted, "centered": centered, "marked": marked, "crossed": crossed}

    def assignKey(self, key, sequence):
        self.keys[key.value] = list(sequence)

    def setLeds(self, leds):
        self.ledsSet = list(leds)

    def fadeLeds(self):
        pass

def _parseEvent(e):
    m = re.fullmatch(r"([kcm])(\d+|[xyw])(p|r|i-?\d+)?", e)
    if not m:
        return None
    return m.group(1), m.group(2), m.group(3) or ""

#Turns recorded event strings back into a friendly action where possible, raw otherwise
def actionFromEvents(press, release):
    if not press and not release:
        return {"type": "none"}
    p = [_parseEvent(e) for e in press]
    r = [_parseEvent(e) for e in release]
    if None not in p and None not in r:
        if p and all(d == "k" and a == "p" for d, c, a in p) and r and all(d == "k" and a == "r" for d, c, a in r) \
           and sorted(c for d, c, a in p) == sorted(c for d, c, a in r) and len(set(c for d, c, a in p)) == len(p):
            #Release order does not matter to the host, a "keys" action always releases in reverse order
            return {"type": "keys", "keys": [KeyboardKeycode(int(c)).name for d, c, a in p]}
        if len(p) == 1 and len(r) == 1 and p[0][1] == r[0][1] and p[0][2] == "p" and r[0][2] == "r":
            if p[0][0] == "c" and r[0][0] == "c":
                return {"type": "media", "key": ConsumerKeycode(int(p[0][1])).name}
            if p[0][0] == "m" and r[0][0] == "m" and p[0][1].isdecimal():
                return {"type": "mouse", "button": MouseKeycode(int(p[0][1])).name}
        if len(p) == 1 and not r and p[0][0] == "m" and p[0][2].startswith("i"):
            return {"type": {"w": "wheel", "x": "mouse_x", "y": "mouse_y"}[p[0][1]], "amount": int(p[0][2][1:])}
        if not r:
            tapped = jogActionFromEvents(press)
            if tapped["type"] == "keys":
                tapped["tap"] = True
                return tapped
    return {"type": "raw", "press": list(press), "release": list(release)}

def jogActionFromEvents(events):
    parsed = [_parseEvent(e) for e in events]
    if not events:
        return {"type": "none"}
    if None not in parsed:
        if len(parsed) == 1:
            d, c, a = parsed[0]
            if d == "m" and a.startswith("i"):
                return {"type": {"w": "wheel", "x": "mouse_x", "y": "mouse_y"}[c], "amount": int(a[1:])}
            if d == "k" and a == "":
                return {"type": "keys", "keys": [KeyboardKeycode(int(c)).name]}
            if d == "c" and a == "":
                return {"type": "media", "key": ConsumerKeycode(int(c)).name}
            if d == "m" and a == "" and c.isdecimal():
                return {"type": "mouse", "button": MouseKeycode(int(c)).name}
        #Presses followed by the releases of the same keys (in any order). A single stroke ("k80") in between is fine too.
        presses = [c for d, c, a in parsed if d == "k" and a == "p"]
        if all(d == "k" for d, c, a in parsed) and presses and len(set(presses)) == len(presses):
            strokes = [c for d, c, a in parsed if a == ""]
            n = len(presses)
            if parsed[:n] == [("k", c, "p") for c in presses] and len(strokes) <= 1:
                rest = parsed[n:]
                middle = [("k", strokes[0], "")] if strokes else []
                releases = rest[len(middle):]
                if rest[:len(middle)] == middle and all(a == "r" for d, c, a in releases) and sorted(c for d, c, a in releases) == sorted(presses):
                    return {"type": "keys", "keys": [KeyboardKeycode(int(c)).name for c in presses + strokes]}
    return {"type": "raw", "events": list(events)}

def _cleanDisplay(tile):
    if tile is None:
        return {}
    d = {k: v for k, v in tile.items() if v not in ("", False, None) or k == "centered"}
    if d.get("centered", True) is True:
        d.pop("centered", None)
    return d

#Runs a Python mode against the recording device and returns a layouts.json entry
def snapshotMode(cls, name, match):
    mode = cls()
    rec = RecordingDevice()
    mode.activate(rec)
    spec = {"name": name, "enabled": False, "match": match, "title": rec.tiles.get("title", {}).get("text", name), "buttons": {}}
    for n in BUTTONS:
        button = {"display": _cleanDisplay(rec.tiles.get(n)),
                  "action": actionFromEvents(rec.keys.get(str(n) + "p", []), rec.keys.get(str(n) + "r", []))}
        spec["buttons"][str(n)] = button
    pythonCallbacks = [k for k in rec.callbacks if k not in (KeyCode.JOG_PRESS.value, KeyCode.JOG.value)]

    #Step through the jog functions by "pressing" the jog dial
    jog = []
    toggle = rec.callbacks.get(KeyCode.JOG_PRESS.value)
    seen = set()
    for i in range(12):
        label = rec.tiles.get(1, {}).get("text", "")
        state = (label, tuple(rec.keys.get("R+", [])), tuple(rec.keys.get("R-", [])))
        if state in seen:
            break
        seen.add(state)
        function = {"label": label, "cw": jogActionFromEvents(rec.keys.get("R+", [])), "ccw": jogActionFromEvents(rec.keys.get("R-", []))}
        if rec.callbacks.get(KeyCode.JOG.value) is not None and getattr(rec.callbacks[KeyCode.JOG.value], "__name__", "") == "showVolume":
            function["show"] = "volume"
        if rec.ledsSet:
            function["flash"] = "#{:06x}".format(rec.ledsSet[0])
        jog.append(function)
        if toggle is None:
            break
        rec.ledsSet = None
        rec.callbacks.pop(KeyCode.JOG.value, None)
        toggle()
        toggle = rec.callbacks.get(KeyCode.JOG_PRESS.value)
    spec["jog"] = jog
    if len(jog) <= 1:
        spec["jogPress"] = actionFromEvents(rec.keys.get("1p", []), rec.keys.get("1r", []))
    if pythonCallbacks:
        spec["notes"] = "Imported from " + cls.__name__ + ". Keys " + ", ".join(sorted(pythonCallbacks)) + " had Python callbacks that a layout cannot express."
    return spec


#Adds every mode class from modes.py that is not in the configuration yet (disabled, so nothing changes until you enable it)
def importPythonModes(config, pythonModes):
    known = set(m.get("python") or m.get("importedFrom") for m in config.get("modes", []))
    added = []
    for name in dir(pythonModes):
        cls = getattr(pythonModes, name)
        if not (name.startswith("Mode") and isinstance(cls, type)) or name in known:
            continue
        label = name[4:] or name
        match = {"type": "window", "pattern": label.lower()}
        try:
            spec = snapshotMode(cls, label, match)
            spec["importedFrom"] = name
        except Exception as e:
            #Modes that need a running service (like OBS) are kept as Python modes
            spec = {"name": label, "enabled": False, "match": match, "python": name,
                    "notes": "Could not be converted (" + type(e).__name__ + ": " + str(e) + "), runs the Python code from modes.py."}
        added.append(spec)
    #Keep modes that match everything at the end, so they do not hide the others
    modes = config.setdefault("modes", [])
    always = [m for m in modes if (m.get("match") or {}).get("type", "always") == "always"]
    config["modes"] = [m for m in modes if m not in always] + added + always
    return added

if __name__ == "__main__":
    if "--import" in sys.argv:
        import modes as pythonModes
        config = loadConfig() if os.path.exists(CONFIG_FILE) else {"version": 1, "modes": []}
        added = importPythonModes(config, pythonModes)
        saveConfig(config)
        for spec in added:
            print("Imported " + spec["name"] + (" (as Python mode)" if spec.get("python") else ""))
        print("Saved " + CONFIG_FILE)
    else:
        print("Usage: python3 configmodes.py --import    (adds the modes from modes.py to layouts.json)")
