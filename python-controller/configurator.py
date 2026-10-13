#!/usr/bin/env python3
#Graphical editor for layouts.json, the modes of the inkkeys macro keyboard.
#
#    python3 configurator.py
#
#Click a key, the screen or the jog dial on the picture of the device to edit it.
#Saving writes layouts.json, which a running controller.py picks up within a second.
#While this window is open, the keyboard shows the mode you are editing (if the controller runs).

import base64
import copy
import io
import json
import os
import re
import time
import tkinter as tk
from tkinter import ttk, messagebox, colorchooser, filedialog

from PIL import Image
from inkkeys import *
from inkkeys.device import BASE_DIR, resolvePath
import configmodes as cm

ICON_DIR = os.path.join(BASE_DIR, "icons")
ACCENT = "#2f6fdf"

#Key names offered in the configurator (one name per keycode, in the order of the HID tables)
KEY_NAMES = [name for name, member in KeyboardKeycode.__members__.items() if member.name == name and member.value >= 4]
MEDIA_NAMES = [name for name, member in ConsumerKeycode.__members__.items() if member.name == name]
MOUSE_NAMES = [name for name in MouseKeycode.__members__]

#Tk key symbols to HID key names. HID codes are positions on a US keyboard, the host applies its layout.
KEYSYMS = {
    "Control_L": "KEY_LEFT_CTRL", "Control_R": "KEY_RIGHT_CTRL", "Shift_L": "KEY_LEFT_SHIFT", "Shift_R": "KEY_RIGHT_SHIFT",
    "Alt_L": "KEY_LEFT_ALT", "Alt_R": "KEY_RIGHT_ALT", "ISO_Level3_Shift": "KEY_RIGHT_ALT", "Meta_L": "KEY_LEFT_ALT", "Meta_R": "KEY_RIGHT_ALT",
    "Super_L": "KEY_LEFT_GUI", "Super_R": "KEY_RIGHT_GUI", "Win_L": "KEY_LEFT_GUI", "Win_R": "KEY_RIGHT_GUI",
    "Return": "KEY_ENTER", "Escape": "KEY_ESC", "BackSpace": "KEY_BACKSPACE", "Tab": "KEY_TAB", "ISO_Left_Tab": "KEY_TAB", "space": "KEY_SPACE",
    "minus": "KEY_MINUS", "underscore": "KEY_MINUS", "equal": "KEY_EQUAL", "plus": "KEY_EQUAL",
    "bracketleft": "KEY_LEFT_BRACE", "braceleft": "KEY_LEFT_BRACE", "bracketright": "KEY_RIGHT_BRACE", "braceright": "KEY_RIGHT_BRACE",
    "backslash": "KEY_BACKSLASH", "bar": "KEY_BACKSLASH", "semicolon": "KEY_SEMICOLON", "colon": "KEY_SEMICOLON",
    "apostrophe": "KEY_QUOTE", "quotedbl": "KEY_QUOTE", "grave": "KEY_TILDE", "asciitilde": "KEY_TILDE",
    "comma": "KEY_COMMA", "less": "KEY_COMMA", "period": "KEY_PERIOD", "greater": "KEY_PERIOD", "slash": "KEY_SLASH", "question": "KEY_SLASH",
    "exclam": "KEY_1", "at": "KEY_2", "numbersign": "KEY_3", "dollar": "KEY_4", "percent": "KEY_5", "asciicircum": "KEY_6",
    "ampersand": "KEY_7", "asterisk": "KEY_8", "parenleft": "KEY_9", "parenright": "KEY_0",
    "Caps_Lock": "KEY_CAPS_LOCK", "Print": "KEY_PRINT", "Scroll_Lock": "KEY_SCROLL_LOCK", "Pause": "KEY_PAUSE",
    "Insert": "KEY_INSERT", "Home": "KEY_HOME", "Prior": "KEY_PAGE_UP", "Delete": "KEY_DELETE", "End": "KEY_END", "Next": "KEY_PAGE_DOWN",
    "Right": "KEY_RIGHT_ARROW", "Left": "KEY_LEFT_ARROW", "Down": "KEY_DOWN_ARROW", "Up": "KEY_UP_ARROW",
    "Num_Lock": "KEY_NUM_LOCK", "Menu": "KEY_APPLICATION",
    "KP_Divide": "KEYPAD_DIVIDE", "KP_Multiply": "KEYPAD_MULTIPLY", "KP_Subtract": "KEYPAD_SUBTRACT", "KP_Add": "KEYPAD_ADD", "KP_Enter": "KEYPAD_ENTER",
    "KP_End": "KEYPAD_1", "KP_Down": "KEYPAD_2", "KP_Next": "KEYPAD_3", "KP_Left": "KEYPAD_4", "KP_Begin": "KEYPAD_5",
    "KP_Right": "KEYPAD_6", "KP_Home": "KEYPAD_7", "KP_Up": "KEYPAD_8", "KP_Prior": "KEYPAD_9", "KP_Insert": "KEYPAD_0",
    "KP_Delete": "KEYPAD_DOT", "KP_Decimal": "KEYPAD_DOT",
}

def keysymToKey(keysym):
    if keysym in KEYSYMS:
        return KEYSYMS[keysym]
    if len(keysym) == 1 and keysym.isalnum():
        return "KEY_" + keysym.upper()
    if re.fullmatch(r"F\d{1,2}", keysym) and "KEY_" + keysym in KeyboardKeycode.__members__:
        return "KEY_" + keysym
    if re.fullmatch(r"KP_\d", keysym):
        return "KEYPAD_" + keysym[3]
    return None

def shortKeyName(name):
    return name[4:] if name.startswith("KEY_") else name

def toPhoto(img, scale=1):
    if scale != 1:
        img = img.convert("L").resize((round(img.width*scale), round(img.height*scale)), Image.NEAREST if scale == int(scale) else Image.BOX)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    return tk.PhotoImage(data=base64.b64encode(buf.getvalue()))


# ==================== Small widgets ====================

class ScrollFrame(ttk.Frame):
    """A vertically scrollable frame, used for the editor panel."""
    def __init__(self, parent, width):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, width=width, highlightthickness=0, borderwidth=0)
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.bar.pack(side="right", fill="y")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.window, width=e.width))
        for seq in ("<Button-4>", "<Button-5>", "<MouseWheel>"):
            self.canvas.bind_all(seq, self.onWheel, add="+")

    def onWheel(self, e):
        widget = self.winfo_containing(e.x_root, e.y_root)
        while widget is not None and widget is not self:
            widget = widget.master
        if widget is None:
            return
        delta = -1 if (getattr(e, "num", 0) == 4 or getattr(e, "delta", 0) > 0) else 1
        self.canvas.yview_scroll(delta, "units")


class FilterCombobox(ttk.Combobox):
    """A combobox that narrows its list to the entries containing the typed text."""
    def __init__(self, parent, values, **kw):
        super().__init__(parent, values=values, **kw)
        self.allValues = list(values)
        self.bind("<KeyRelease>", self.onKey)

    def onKey(self, e):
        if e.keysym in ("Return", "Down", "Up", "Escape", "Tab"):
            return
        text = self.get().lower()
        self.configure(values=[v for v in self.allValues if text in v.lower()] or self.allValues)


class KeyRecorder(tk.Toplevel):
    """Modal window that records a key combination: hold the keys, release them to finish."""
    def __init__(self, parent, onDone):
        super().__init__(parent)
        self.title("Record keys")
        self.transient(parent)
        self.resizable(False, False)
        self.onDone = onDone
        self.order = []
        self.down = set()
        frame = ttk.Frame(self, padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Press the key combination now.", font=("TkDefaultFont", 11, "bold")).pack()
        ttk.Label(frame, text="It is saved when you release all keys.\nShortcuts your desktop grabs (like Super+L) may not\narrive here, add those with the key list instead.", justify="center").pack(pady=(6, 10))
        self.shown = ttk.Label(frame, text=" ", font=("TkDefaultFont", 14))
        self.shown.pack(pady=6)
        ttk.Button(frame, text="Cancel", command=self.destroy).pack(pady=(8, 0))
        self.bind("<KeyPress>", self.onPress)
        self.bind("<KeyRelease>", self.onRelease)
        self.update_idletasks()
        self.geometry("+%d+%d" % (parent.winfo_rootx() + 200, parent.winfo_rooty() + 150))
        self.grab_set()
        self.focus_force()

    def onPress(self, e):
        key = keysymToKey(e.keysym)
        if key is None:
            self.shown.configure(text="Unknown key: " + e.keysym)
            return
        self.down.add(key)
        if key not in self.order:
            self.order.append(key)
        self.shown.configure(text=" + ".join(cm.keyLabel(k) for k in self.order))
        return "break"

    def onRelease(self, e):
        key = keysymToKey(e.keysym)
        self.down.discard(key)
        #Key repeat sends release/press pairs while a key is held, so wait a moment before finishing
        self.after(80, self.checkDone)
        return "break"

    def checkDone(self):
        if self.order and not self.down and self.winfo_exists():
            #Modifiers first, like you would press them
            modifiers = [k for k in self.order if k.startswith(("KEY_LEFT_", "KEY_RIGHT_")) and k.split("_")[-1] in ("CTRL", "SHIFT", "ALT", "GUI")]
            keys = modifiers + [k for k in self.order if k not in modifiers]
            self.grab_release()
            self.destroy()
            self.onDone(keys)


class IconPicker(tk.Toplevel):
    """Searchable grid of the icons in the icons folder."""
    COLS = 10
    CELL = 52
    LIMIT = 300

    cache = {}

    def __init__(self, parent, onPick):
        super().__init__(parent)
        self.title("Choose an icon")
        self.transient(parent)
        self.onPick = onPick
        self.files = sorted(f for f in os.listdir(ICON_DIR) if f.lower().endswith(".png"))
        top = ttk.Frame(self, padding=(10, 10, 10, 0))
        top.pack(fill="x")
        ttk.Label(top, text="Search:").pack(side="left")
        self.query = tk.StringVar()
        entry = ttk.Entry(top, textvariable=self.query, width=30)
        entry.pack(side="left", padx=6)
        ttk.Button(top, text="Other file…", command=self.browse).pack(side="right")
        self.info = ttk.Label(self, text="", padding=(10, 4))
        self.info.pack(fill="x")
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.canvas = tk.Canvas(body, width=self.COLS*self.CELL, height=7*self.CELL, background="white", highlightthickness=0)
        bar = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.canvas.bind("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"))
        self.canvas.bind("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"))
        self.canvas.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        self.query.trace_add("write", lambda *a: self.after_idle(self.fill))
        self.fill()
        self.geometry("+%d+%d" % (parent.winfo_rootx() + 120, parent.winfo_rooty() + 80))
        entry.focus_set()

    def photo(self, f):
        if f not in self.cache:
            self.cache[f] = toPhoto(Image.open(os.path.join(ICON_DIR, f)))
        return self.cache[f]

    def fill(self):
        self.canvas.delete("all")
        words = self.query.get().lower().split()
        matches = [f for f in self.files if all(w in f.lower() for w in words)]
        self.info.configure(text=str(len(matches)) + " icons" + (" (showing the first " + str(self.LIMIT) + ", search to narrow down)" if len(matches) > self.LIMIT else "") + ". Click one to use it.")
        for i, f in enumerate(matches[:self.LIMIT]):
            x = (i % self.COLS) * self.CELL + self.CELL // 2
            y = (i // self.COLS) * self.CELL + self.CELL // 2
            tag = "icon%d" % i
            self.canvas.create_rectangle(x-25, y-25, x+25, y+25, outline="", fill="white", tags=(tag, "bg"))
            self.canvas.create_image(x, y, image=self.photo(f), tags=(tag,))
            self.canvas.tag_bind(tag, "<Button-1>", lambda e, f=f: self.pick("icons/" + f))
            self.canvas.tag_bind(tag, "<Enter>", lambda e, f=f, tag=tag: (self.info.configure(text=f[:-4]), self.canvas.itemconfigure(tag + "&&bg", fill="#dde8ff")))
            self.canvas.tag_bind(tag, "<Leave>", lambda e, tag=tag: self.canvas.itemconfigure(tag + "&&bg", fill="white"))
        rows = (min(len(matches), self.LIMIT) + self.COLS - 1) // self.COLS
        self.canvas.configure(scrollregion=(0, 0, self.COLS*self.CELL, max(rows*self.CELL, 1)))
        self.canvas.yview_moveto(0)

    def browse(self):
        path = filedialog.askopenfilename(parent=self, title="Icon image", filetypes=[("Images", "*.png *.gif *.bmp"), ("All files", "*")])
        if path:
            self.pick(os.path.relpath(path, BASE_DIR) if path.startswith(BASE_DIR) else path)

    def pick(self, path):
        self.destroy()
        self.onPick(path)


# ==================== Action editor ====================

class ActionEditor(ttk.Frame):
    """Edits one action (what a key or a jog step does). Writes into the dict returned by get().
    kind: "button" (held while the key is held), "jog" (one dial step) or "gesture" (runs once, for hold,
    double tap and combos; the controller runs these, so they can type text and have any length)."""
    def __init__(self, parent, app, get, set, jog=False, kind=None, onType=None):
        super().__init__(parent)
        self.onTypeChanged = onType
        self.kind = kind or ("jog" if jog else "button")
        self.app, self.get, self.set = app, get, set
        self.jog = self.kind != "button"
        #Typing and launching run once per action, not once per step of the dial
        types = [(k, v) for k, v in cm.ACTION_TYPES.items() if k not in cm.CONTROLLER_TYPES or self.kind != "jog"]
        self.typeNames = [label for key, label in types]
        self.typeKeys = [key for key, label in types]
        row = ttk.Frame(self)
        row.pack(fill="x")
        self.typeVar = tk.StringVar(value=cm.ACTION_TYPES.get(self.action().get("type", "none"), "Nothing"))
        box = ttk.Combobox(row, textvariable=self.typeVar, values=self.typeNames, state="readonly", width=26)
        box.pack(side="left")
        box.bind("<<ComboboxSelected>>", self.onType)
        self.body = ttk.Frame(self)
        self.body.pack(fill="x", pady=(4, 0))
        self.problem = ttk.Label(self, foreground="#c0392b", wraplength=380)
        self.problem.pack(fill="x")
        self.build()

    def action(self):
        a = self.get()
        if a is None:
            a = {"type": "none"}
            self.set(a)
        return a

    def onType(self, e=None):
        t = self.typeKeys[self.typeNames.index(self.typeVar.get())]
        old = self.action()
        new = {"type": t}
        for keep in ("label", "icon"): #What the screen shows for a combo
            if keep in old:
                new[keep] = old[keep]
        if t == "keys":
            new["keys"] = old.get("keys", [])
        elif t == "media":
            new["key"] = "MEDIA_PLAY_PAUSE"
        elif t == "mouse":
            new["button"] = "MOUSE_LEFT"
        elif t in cm.AXES:
            new["amount"] = old.get("amount", 1)
        elif t == "text":
            new["text"] = old.get("text", "")
        elif t == "open":
            new["target"] = old.get("target", "https://")
        elif t == "command":
            new["command"] = old.get("command", "")
        elif t == "raw":
            if self.jog:
                new["events"] = cm.tapEvents(old)
            else:
                press, release = cm.buttonEvents(old)
                new["press"], new["release"] = press, release
        self.set(new)
        self.build()
        self.app.changed()
        if self.onTypeChanged:
            self.onTypeChanged()

    def build(self):
        for w in self.body.winfo_children():
            w.destroy()
        a = self.action()
        t = a.get("type", "none")
        if t == "keys":
            self.buildKeys(a)
        elif t == "media":
            self.buildChoice(a, "key", MEDIA_NAMES)
        elif t == "mouse":
            self.buildChoice(a, "button", MOUSE_NAMES)
        elif t in cm.AXES:
            var = tk.IntVar(value=int(a.get("amount", 1)))
            def onAmount(*args):
                try:
                    a["amount"] = max(-127, min(127, int(var.get())))
                except (tk.TclError, ValueError):
                    return
                self.app.changed()
            var.trace_add("write", onAmount)
            ttk.Label(self.body, text="Amount per step:").pack(side="left")
            ttk.Spinbox(self.body, from_=-127, to=127, textvariable=var, width=6).pack(side="left", padx=4)
            ttk.Label(self.body, text="(negative = other direction)", foreground="#666").pack(side="left")
        elif t == "raw":
            self.buildRaw(a)
        elif t == "text":
            self.buildText(a)
        elif t in ("open", "command"):
            self.buildLaunch(a, "target" if t == "open" else "command")
        self.validate()

    def buildLaunch(self, a, field):
        for key, label, hint in ((field, "Website / file:" if field == "target" else "Command:", None), ("label", "Short name:", "shown on the key cap")):
            row = ttk.Frame(self.body)
            row.pack(fill="x", pady=1)
            ttk.Label(row, text=label, width=13).pack(side="left")
            var = tk.StringVar(value=a.get(key, ""))
            def onEdit(*args, var=var, key=key):
                if var.get().strip() or key != "label":
                    a[key] = var.get().strip()
                else:
                    a.pop(key, None)
                self.app.changed()
                self.validate()
            var.trace_add("write", onEdit)
            ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True)
            if hint:
                ttk.Label(row, text=hint, foreground="#666").pack(side="left", padx=(4, 0))
        row = ttk.Frame(self.body)
        row.pack(fill="x", pady=(2, 0))
        ttk.Button(row, text="Test", command=lambda: cm.launch(a)).pack(side="left")
        ttk.Label(row, foreground="#666", wraplength=320, justify="left",
                  text=("Opened with your default browser or program (xdg-open)." if field == "target" else
                        "Runs in the background through the shell. Installed Chrome web apps start with\n"
                        "google-chrome --profile-directory=Default --app-id=<id> (see ~/.local/share/applications).")
                       + " Needs the controller to be running.").pack(side="left", padx=(6, 0))

    def buildText(self, a):
        box = tk.Text(self.body, height=3, width=40, wrap="word", undo=True)
        box.insert("1.0", a.get("text", ""))
        box.pack(fill="x")
        def onEdit(e=None):
            a["text"] = box.get("1.0", "end-1c")
            self.app.changed()
            self.validate()
        box.bind("<KeyRelease>", onEdit)
        box.bind("<<Paste>>", lambda e: self.after(10, onEdit))
        ttk.Label(self.body, foreground="#666", wraplength=380, justify="left",
                  text="Typed through the keyboard when the action runs, line breaks press Enter. Needs the controller to be running. "
                       "Old X11 programs that use an input method (like xterm) may scramble fast typing.").pack(fill="x", pady=(2, 0))

    def buildChoice(self, a, field, names):
        var = tk.StringVar(value=a.get(field, names[0]))
        box = FilterCombobox(self.body, names, textvariable=var, width=30)
        box.pack(side="left")
        def onPick(*args):
            if var.get() in names:
                a[field] = var.get()
                self.app.changed()
                self.validate()
        box.bind("<<ComboboxSelected>>", onPick)
        box.bind("<FocusOut>", onPick)

    def buildKeys(self, a):
        keys = a.setdefault("keys", [])
        line = ttk.Frame(self.body)
        line.pack(fill="x")
        shown = ttk.Label(line, text=cm.describeAction(dict(a, tap=False)) if keys else "(no keys yet)", font=("TkDefaultFont", 11, "bold"))
        shown.pack(side="left")
        buttons = ttk.Frame(self.body)
        buttons.pack(fill="x", pady=(4, 0))
        def setKeys(newKeys):
            a["keys"] = newKeys
            self.build()
            self.app.changed()
        ttk.Button(buttons, text="Record…", command=lambda: KeyRecorder(self.winfo_toplevel(), setKeys)).pack(side="left")
        ttk.Button(buttons, text="Remove last", command=lambda: setKeys(keys[:-1])).pack(side="left", padx=4)
        ttk.Button(buttons, text="Clear", command=lambda: setKeys([])).pack(side="left")
        add = ttk.Frame(self.body)
        add.pack(fill="x", pady=(4, 0))
        ttk.Label(add, text="Add key:").pack(side="left")
        var = tk.StringVar()
        names = [shortKeyName(k) for k in KEY_NAMES]
        box = FilterCombobox(add, names, textvariable=var, width=18)
        box.pack(side="left", padx=4)
        def onAdd(*args):
            name = var.get().strip().upper()
            full = name if name.startswith("KEYPAD_") else "KEY_" + name
            if full in KeyboardKeycode.__members__:
                setKeys(keys + [KeyboardKeycode[full].name])
        box.bind("<<ComboboxSelected>>", onAdd)
        box.bind("<Return>", onAdd)
        if not self.jog:
            tap = tk.BooleanVar(value=a.get("tap", False))
            def onTap(*args):
                if tap.get():
                    a["tap"] = True
                else:
                    a.pop("tap", None)
                self.app.changed()
                self.validate()
            tap.trace_add("write", onTap)
            ttk.Checkbutton(self.body, text="Tap once on press (instead of holding while pressed)", variable=tap).pack(anchor="w", pady=(4, 0))

    def buildRaw(self, a):
        fields = [("events", "Events per step:")] if self.jog else [("press", "On press:"), ("release", "On release:")]
        for field, label in fields:
            line = ttk.Frame(self.body)
            line.pack(fill="x", pady=1)
            ttk.Label(line, text=label, width=11).pack(side="left")
            var = tk.StringVar(value=" ".join(a.get(field, [])))
            def onEdit(*args, var=var, field=field):
                a[field] = var.get().split()
                self.app.changed()
                self.validate()
            var.trace_add("write", onEdit)
            ttk.Entry(line, textvariable=var).pack(side="left", fill="x", expand=True)
        ttk.Label(self.body, foreground="#666", wraplength=380, justify="left",
                  text="Device protocol: k<code>p / k<code>r press / release a key, k<code> taps it, c<code> for media keys, m<button> for mouse buttons, mwi<n> / mxi<n> / myi<n> for wheel and movement, d<ms> waits. Codes are HID usage numbers.").pack(fill="x", pady=(2, 0))

    def validate(self):
        problems = cm.validateAction(self.action(), jog=self.jog, limit=self.kind != "gesture")
        self.problem.configure(text="\n".join(problems))


# ==================== Main window ====================

class Configurator(tk.Tk):
    def __init__(self):
        super().__init__(className="inkkeys-configurator")
        self.title("inkkeys configurator")
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Accent.TButton", foreground="white", background=ACCENT)
        style.map("Accent.TButton", background=[("active", "#2559b8"), ("disabled", "#9db3dd")])

        self.device = Device() #Only used to render the screen, never connected
        self.scale = 2 if self.winfo_screenheight() >= 900 else 1.5
        self.modeIndex = 0
        self.slot = "mode"
        self.jogIndex = 0
        self.photos = []       #Tk forgets images that Python no longer references, so keep them here
        self.editorPhotos = []
        self.previewAfter = None

        self.load()
        self.buildUi()
        self.selectMode(self.firstEnabled())
        self.protocol("WM_DELETE_WINDOW", self.onClose)
        self.bind_all("<Control-s>", lambda e: self.save())
        self.keepPreviewAlive()
        self.watchConfigFile()

    # ----- Data -----

    def load(self):
        if os.path.exists(cm.CONFIG_FILE):
            self.config = cm.loadConfig()
        else:
            #First start: build the configuration from the Python modes
            self.config = {"version": 1, "modes": []}
            try:
                import modes as pythonModes
                cm.importPythonModes(self.config, pythonModes)
            except Exception as e:
                print("modes.py could not be imported: " + str(e))
            for m in self.config["modes"]:
                if m.get("importedFrom") == "ModeFallback":
                    m.update({"name": "General", "enabled": True, "match": {"type": "always"}})
        if not self.config.get("modes"):
            self.config["modes"] = [self.newMode("General", {"type": "always"})]
        self.savedState = self.normalizedState()
        self.savedMtime = self.configMtime()

    def configMtime(self):
        try:
            return os.path.getmtime(cm.CONFIG_FILE)
        except OSError:
            return None

    #layouts.json may also be changed by another program or a second configurator.
    #Reload it if there is nothing to lose, otherwise save() asks before overwriting.
    def watchConfigFile(self):
        mtime = self.configMtime()
        if mtime != self.savedMtime and not self.dirty():
            name = self.mode().get("name")
            try:
                self.load()
            except (OSError, ValueError):
                pass
            else:
                names = [m.get("name") for m in self.config["modes"]]
                self.selectMode(names.index(name) if name in names else 0)
                self.status.configure(text="Reloaded, layouts.json was changed outside the configurator")
        self.after(2000, self.watchConfigFile)

    def newMode(self, name, match):
        return {"name": name, "enabled": True, "match": match, "title": name,
                "buttons": {str(n): {"display": {}, "action": {"type": "none"}} for n in cm.BUTTONS},
                "jog": [{"label": "Mouse Wheel", "cw": {"type": "wheel", "amount": -1}, "ccw": {"type": "wheel", "amount": 1}}]}

    def mode(self):
        return self.config["modes"][self.modeIndex]

    #The configuration as it would be saved (empty gestures dropped), so merely looking at a key is no change
    def normalizedState(self, config=None):
        config = copy.deepcopy(self.config if config is None else config)
        self.dropEmptyGestures(config)
        return json.dumps(config, sort_keys=True)

    def dirty(self):
        return self.normalizedState() != self.savedState

    def firstEnabled(self):
        for i, m in enumerate(self.config["modes"]):
            if m.get("enabled", True) and not m.get("python"):
                return i
        return 0

    # ----- Layout -----

    def buildUi(self):
        root = ttk.Frame(self, padding=8)
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=0)
        root.columnconfigure(2, weight=1)
        root.rowconfigure(0, weight=1)

        #Modes list
        left = ttk.Frame(root)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 8))
        ttk.Label(left, text="Modes", font=("TkDefaultFont", 11, "bold")).pack(anchor="w")
        ttk.Label(left, text="The first enabled mode that\nmatches the active window wins.", foreground="#666").pack(anchor="w", pady=(0, 4))
        self.modeList = tk.Listbox(left, width=26, height=18, activestyle="none", exportselection=False, selectbackground=ACCENT)
        self.modeList.pack(fill="y", expand=True)
        self.modeList.bind("<<ListboxSelect>>", lambda e: self.modeList.curselection() and self.selectMode(self.modeList.curselection()[0]))
        grid = ttk.Frame(left)
        grid.pack(fill="x", pady=(6, 0))
        for i, (text, cmd) in enumerate([("Add", self.addMode), ("Duplicate", self.duplicateMode), ("Delete", self.deleteMode),
                                         ("Move up", lambda: self.moveMode(-1)), ("Move down", lambda: self.moveMode(1)), ("Import…", self.importModes)]):
            ttk.Button(grid, text=text, command=cmd, width=10).grid(row=i//2, column=i%2, sticky="ew", padx=1, pady=1)
        ttk.Button(left, text="Cheat sheet for this mode…", command=self.showCheatSheet).pack(fill="x", pady=(8, 1))
        ttk.Button(left, text="Settings…", command=self.showSettings).pack(fill="x", pady=1)

        #Device picture
        W, H = self.device.dispW, self.device.dispH
        s = self.scale
        self.keyW = 84
        self.screenX = 30 + self.keyW + 18
        self.screenY = 24
        cw = self.screenX*2 + W*s
        ch = self.screenY + H*s + 140
        self.canvas = tk.Canvas(root, width=cw, height=ch, highlightthickness=0, background=self.cget("background"))
        self.canvas.grid(row=0, column=1, sticky="n")
        self.canvas.bind("<Button-1>", self.onCanvasClick)
        self.canvas.bind("<Motion>", self.onCanvasMotion)
        self.hitAreas = []

        #Editor panel
        self.editorScroll = ScrollFrame(root, width=440)
        self.editorScroll.grid(row=0, column=2, sticky="nsew", padx=(8, 0))
        self.editor = self.editorScroll.inner

        #Bottom bar
        bottom = ttk.Frame(self, padding=(8, 0, 8, 8))
        bottom.pack(fill="x")
        self.livePreview = tk.BooleanVar(value=True)
        ttk.Checkbutton(bottom, text="Show the mode I am editing on the keyboard (needs a running controller.py)", variable=self.livePreview,
                        command=self.schedulePreview).pack(side="left")
        self.saveButton = ttk.Button(bottom, text="Save", style="Accent.TButton", command=self.save)
        self.saveButton.pack(side="right")
        ttk.Button(bottom, text="Revert", command=self.revert).pack(side="right", padx=6)
        self.status = ttk.Label(bottom, text="", foreground="#666")
        self.status.pack(side="right", padx=10)

    # ----- Mode list -----

    def refreshModeList(self):
        self.modeList.delete(0, "end")
        reachable = True
        for i, m in enumerate(self.config["modes"]):
            enabled = m.get("enabled", True)
            match = m.get("match") or {"type": "always"}
            label = m.get("name", "?")
            if not enabled:
                label += "  (off)"
            elif not reachable:
                label += "  (never reached)"
            elif match.get("type", "always") == "always":
                label += "  (fallback)"
            self.modeList.insert("end", label)
            self.modeList.itemconfigure(i, foreground="#999" if not enabled else ("#c0392b" if not reachable else "black"))
            if enabled and match.get("type", "always") == "always":
                reachable = False
        self.modeList.selection_clear(0, "end")
        self.modeList.selection_set(self.modeIndex)
        self.modeList.see(self.modeIndex)

    def selectMode(self, index):
        self.modeIndex = max(0, min(index, len(self.config["modes"]) - 1))
        self.jogIndex = 0
        self.refreshModeList()
        self.selectSlot("mode")
        self.schedulePreview()

    def addMode(self):
        m = self.newMode("New mode", {"type": "window", "pattern": ""})
        modes = self.config["modes"]
        #Insert before the fallback modes so it can be reached
        index = next((i for i, x in enumerate(modes) if x.get("enabled", True) and (x.get("match") or {}).get("type", "always") == "always"), len(modes))
        modes.insert(index, m)
        self.selectMode(index)
        self.changed()

    def duplicateMode(self):
        m = copy.deepcopy(self.mode())
        m["name"] = m.get("name", "") + " copy"
        self.config["modes"].insert(self.modeIndex + 1, m)
        self.selectMode(self.modeIndex + 1)
        self.changed()

    def deleteMode(self):
        if len(self.config["modes"]) <= 1:
            return
        if messagebox.askyesno("Delete mode", "Delete the mode \"" + self.mode().get("name", "") + "\"?", parent=self):
            del self.config["modes"][self.modeIndex]
            self.selectMode(self.modeIndex)
            self.changed()

    def moveMode(self, delta):
        modes = self.config["modes"]
        j = self.modeIndex + delta
        if 0 <= j < len(modes):
            modes[self.modeIndex], modes[j] = modes[j], modes[self.modeIndex]
            self.modeIndex = j
            self.refreshModeList()
            self.changed()

    def importModes(self):
        try:
            import modes as pythonModes
        except Exception as e:
            messagebox.showerror("Import", "modes.py could not be loaded:\n" + str(e), parent=self)
            return
        added = cm.importPythonModes(self.config, pythonModes)
        if added:
            messagebox.showinfo("Import", "Imported (disabled until you enable them):\n" + "\n".join(m["name"] for m in added), parent=self)
            self.selectMode(self.config["modes"].index(added[0]))
            self.changed()
        else:
            messagebox.showinfo("Import", "All classes from modes.py are already in the list.", parent=self)

    # ----- Device picture -----

    def tileRect(self, function):
        """Where a tile appears on screen, in unscaled pixels (the panel content is rotated by 180°)."""
        x, y, w, h = self.device.getAreaFor(function)
        return self.device.dispW - x - w, self.device.dispH - y - h, w, h

    def renderScreen(self):
        m = self.mode()
        img = Image.new("1", (self.device.dispW, self.device.dispH), 1)
        if m.get("python"):
            return img
        def paste(function, tile):
            x, y, w, h = self.tileRect(function)
            img.paste(tile, (x, y))
        paste("title", self.device.renderTextFor("title", m.get("title", m.get("name", "")), inverted=True))
        jog = m.get("jog", [])
        paste(1, self.device.renderTextFor(1, jog[min(self.jogIndex, len(jog)-1)].get("label", "") if jog else ""))
        for n in cm.BUTTONS:
            d = m.get("buttons", {}).get(str(n), {}).get("display") or {}
            try:
                if d.get("icon"):
                    tile = self.device.renderIconFor(n, d["icon"], inverted=d.get("inverted", False), centered=d.get("centered", True),
                                                     marked=d.get("marked", False), crossed=d.get("crossed", False))
                else:
                    tile = self.device.renderTextFor(n, d.get("text", ""), d.get("subtext", ""), inverted=d.get("inverted", False))
            except OSError:
                tile = self.device.renderTextFor(n, "missing icon")
            paste(n, tile)
        return img

    def drawDevice(self):
        c = self.canvas
        c.delete("all")
        self.photos = []
        s = self.scale
        W, H = self.device.dispW, self.device.dispH
        sx, sy = self.screenX, self.screenY
        m = self.mode()
        python = bool(m.get("python"))

        #Body
        c.create_rectangle(16, 6, int(c.cget("width")) - 16, int(c.cget("height")) - 6, fill="#3a3d42", outline="#2a2c30", width=2)
        #Screen
        c.create_rectangle(sx - 6, sy - 6, sx + W*s + 6, sy + H*s + 6, fill="#d9d9d4", outline="#1d1f22", width=2)
        photo = toPhoto(self.renderScreen(), s)
        self.photos.append(photo)
        c.create_image(sx, sy, image=photo, anchor="nw")
        if python:
            c.create_text(sx + W*s/2, sy + H*s/2, text="Defined in modes.py\n(" + m["python"] + ")", justify="center", fill="#555")

        #Clickable areas: (x0, y0, x1, y1, slot), checked in order by onCanvasClick
        self.hitAreas = []
        for function, slot in [("title", "mode"), (1, "jog")] + [(n, n) for n in cm.BUTTONS]:
            x, y, w, h = self.tileRect(function)
            area = (sx + x*s, sy + y*s, sx + (x+w)*s, sy + (y+h)*s)
            self.hitAreas.append(area + (slot,))
            if self.slot == slot:
                c.create_rectangle(*area, outline=ACCENT, width=3)

        #Combos of the selected key (blue: hold it and press these) and combos that end with it (amber)
        gestures = {} if python else {k: cm.gesturesFor(m, k) for k in range(1, 10)}
        selectedKey = 1 if self.slot == "jog" else (self.slot if self.slot in cm.BUTTONS else None)
        partners = gestures[selectedKey]["combos"] if selectedKey else {}
        holders = {h: g["combos"][selectedKey] for h, g in gestures.items() if selectedKey in g["combos"]} if selectedKey else {}
        selectedName = "dial" if selectedKey == 1 else str(selectedKey)

        def badges(k):
            g = gestures.get(k)
            if not g:
                return ""
            marks = (["hold"] if g["long"] else []) + (["2\u00d7"] if g["double"] else []) + (["+" + str(len(g["combos"]))] if g["combos"] else [])
            return "  ".join(marks)

        #Keys next to the screen
        for n in cm.BUTTONS:
            x, y, w, h = self.tileRect(n)
            cy = sy + (y + h/2) * s
            left = x < W/2
            kx = sx - 18 - self.keyW if left else sx + W*s + 18
            tag = "key_" + str(n)
            selected = self.slot == n
            fill = "#bbb" if python else "#dbe7ff" if n in partners else "#ffecc7" if n in holders else "#f4f4f2"
            c.create_rectangle(kx, cy - 38, kx + self.keyW, cy + 38, fill=fill,
                               outline=ACCENT if selected else "#16181b", width=4 if selected else 2, tags=(tag,))
            self.hitAreas.append((kx, cy - 38, kx + self.keyW, cy + 38, n))
            c.create_text(kx + 7, cy - 31, text=str(n), anchor="nw", fill="#888", font=("TkDefaultFont", 8), tags=(tag,))
            action = m.get("buttons", {}).get(str(n), {}).get("action")
            if n in partners:
                text, color = "with " + selectedName + ":\n" + cm.describeAction(partners[n]), ACCENT
            elif n in holders:
                text, color = "hold, then " + selectedName + ":\n" + cm.describeAction(holders[n]), "#9a6400"
            else:
                text, color = ("" if python else cm.describeAction(action)), "black"
            c.create_text(kx + self.keyW/2, cy + 2, text=text, width=self.keyW - 8, justify="center", fill=color,
                          font=("TkDefaultFont", 8), tags=(tag,))
            c.create_text(kx + self.keyW/2, cy + 30, text=badges(n), fill=ACCENT, font=("TkDefaultFont", 7, "bold"), tags=(tag,))

        #Jog dial
        kx, ky, r = sx + W*s/2, sy + H*s + 70, 46
        selected = self.slot == "jog"
        c.create_oval(kx - r, ky - r, kx + r, ky + r, fill="#55585e", outline=ACCENT if selected else "#16181b", width=4 if selected else 2, tags=("knob",))
        c.create_oval(kx - r + 10, ky - r + 10, kx + r - 10, ky + r - 10, fill="#62666c", outline="", tags=("knob",))
        c.create_text(kx, ky, text="Jog dial\n(1)", fill="white", justify="center", font=("TkDefaultFont", 9), tags=("knob",))
        if 1 in partners or 1 in holders:
            text = ("with " + selectedName + ": " + cm.describeAction(partners[1])) if 1 in partners else ("hold, then " + selectedName + ": " + cm.describeAction(holders[1]))
            c.create_text(kx + r + 12, ky, text=text, anchor="w", width=150, fill=ACCENT if 1 in partners else "#ffd27a", font=("TkDefaultFont", 8))
        dialMarks = badges(1)
        jogFunctions = m.get("jog", [])
        if any(cm.isSet(f.get("pressCw")) or cm.isSet(f.get("pressCcw")) for f in jogFunctions):
            dialMarks = (dialMarks + "  press+turn").strip()
        if dialMarks:
            c.create_text(kx - r - 12, ky, text=dialMarks, anchor="e", fill="#a9c4ff", font=("TkDefaultFont", 8, "bold"))
        self.hitAreas.append((kx - r, ky - r, kx + r, ky + r, "jog"))

    def hitSlot(self, x, y):
        for x0, y0, x1, y1, slot in self.hitAreas:
            if x0 <= x <= x1 and y0 <= y <= y1:
                return slot
        return None

    def onCanvasClick(self, e):
        slot = self.hitSlot(e.x, e.y)
        if slot is not None:
            self.selectSlot(slot)

    def onCanvasMotion(self, e):
        self.canvas.configure(cursor="hand2" if self.hitSlot(e.x, e.y) is not None else "")

    # ----- Editor panel -----

    def selectSlot(self, slot):
        self.slot = slot
        self.drawDevice()
        for w in self.editor.winfo_children():
            w.destroy()
        self.editorPhotos = []
        self.buildModeEditor(self.editor)
        if self.mode().get("python"):
            pass
        elif slot == "jog":
            self.buildJogEditor(self.editor)
        elif slot in cm.BUTTONS:
            self.buildButtonEditor(self.editor, slot)
        else:
            ttk.Label(self.editor, text="Click a key, a part of the screen or the jog dial to edit it.", foreground="#666", padding=(0, 12)).pack(anchor="w")
        self.editorScroll.canvas.yview_moveto(0)

    def field(self, parent, label, value, onChange, width=30):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text=label, width=14).pack(side="left")
        var = tk.StringVar(value=value)
        var.trace_add("write", lambda *a: onChange(var.get()))
        entry = ttk.Entry(row, textvariable=var, width=width)
        entry.pack(side="left", fill="x", expand=True)
        return var, entry, row

    def buildModeEditor(self, parent):
        m = self.mode()
        box = ttk.LabelFrame(parent, text="Mode", padding=8)
        box.pack(fill="x", pady=(0, 8))

        def setName(v):
            m["name"] = v
            self.changed(redraw=False)
            self.refreshModeList()
        self.field(box, "Name:", m.get("name", ""), setName)
        if not m.get("python"):
            def setTitle(v):
                m["title"] = v
                self.changed()
            self.field(box, "Screen title:", m.get("title", ""), setTitle)

        enabled = tk.BooleanVar(value=m.get("enabled", True))
        def setEnabled(*a):
            m["enabled"] = enabled.get()
            self.refreshModeList()
            self.changed(redraw=False)
        enabled.trace_add("write", setEnabled)
        ttk.Checkbutton(box, text="Enabled", variable=enabled).pack(anchor="w", pady=(2, 4))

        match = m.setdefault("match", {"type": "always"})
        kinds = [("always", "Always (fallback)"), ("window", "Active window matches"), ("process", "A process is running")]
        row = ttk.Frame(box)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Active when:", width=14).pack(side="left")
        kindVar = tk.StringVar(value=dict(kinds).get(match.get("type", "always")))
        kindBox = ttk.Combobox(row, textvariable=kindVar, values=[k[1] for k in kinds], state="readonly", width=24)
        kindBox.pack(side="left")
        detail = ttk.Frame(box)
        detail.pack(fill="x")

        def buildDetail():
            for w in detail.winfo_children():
                w.destroy()
            t = match.get("type", "always")
            if t == "window":
                def setPattern(v):
                    match["pattern"] = v
                    try:
                        re.compile(v)
                        hint.configure(text="Regular expression, matched anywhere in the window's \"instance class\" name, ignoring case.", foreground="#666")
                    except re.error as e:
                        hint.configure(text="Invalid pattern: " + str(e), foreground="#c0392b")
                    self.changed(redraw=False)
                var, entry, row = self.field(detail, "Window class:", match.get("pattern", ""), setPattern, width=22)
                button = ttk.Button(row, text="Detect…", command=lambda: self.detectWindow(var, button))
                entry.pack_forget() #Pack the button first, so it keeps its full width
                button.pack(side="right", padx=(4, 0))
                entry.pack(side="left", fill="x", expand=True)
                hint = ttk.Label(detail, text="Regular expression, matched anywhere in the window's \"instance class\" name, ignoring case.", foreground="#666", wraplength=400)
                hint.pack(anchor="w")
            elif t == "process":
                def setProcess(v):
                    match["name"] = v
                    self.changed(redraw=False)
                var, entry, row = self.field(detail, "Process name:", match.get("name", ""), setProcess)
                ttk.Button(row, text="Pick…", command=lambda: self.pickProcess(var)).pack(side="left", padx=(4, 0))
            else:
                ttk.Label(detail, text="Used when no mode above it matches. Modes below an enabled fallback are never used.", foreground="#666", wraplength=400).pack(anchor="w")

        def setKind(e=None):
            match.clear()
            match["type"] = [k[0] for k in kinds if k[1] == kindVar.get()][0]
            buildDetail()
            self.refreshModeList()
            self.changed(redraw=False)
        kindBox.bind("<<ComboboxSelected>>", setKind)
        buildDetail()

        if m.get("python"):
            ttk.Label(box, wraplength=400, justify="left", foreground="#555",
                      text="This mode runs Python code from modes.py (" + m["python"] + "), so its keys and screen are defined there. "
                           "You can still choose when it is active and where it sits in the list.").pack(anchor="w", pady=(6, 0))
        if m.get("notes"):
            ttk.Label(box, text=m["notes"], wraplength=400, justify="left", foreground="#8a6d00").pack(anchor="w", pady=(6, 0))

    def detectWindow(self, var, button):
        try:
            from processchecks import getActiveWindow
        except Exception as e:
            messagebox.showerror("Detect", "Cannot read the active window: " + str(e), parent=self)
            return
        def count(n):
            if n > 0:
                button.configure(text="Switch window… " + str(n), state="disabled")
                self.after(1000, lambda: count(n - 1))
            else:
                window = getActiveWindow()
                button.configure(text="Detect…", state="normal")
                if window:
                    var.set(re.escape(window.split(" ")[-1])) #The class part names the app, see processchecks.py
                    self.status.configure(text="Detected window class \"" + window + "\"")
                else:
                    self.status.configure(text="Could not detect the window class")
        count(3)

    def pickProcess(self, var):
        try:
            import psutil
            names = sorted({p.info["name"] for p in psutil.process_iter(["name"]) if p.info["name"]}, key=str.lower)
        except Exception as e:
            messagebox.showerror("Processes", str(e), parent=self)
            return
        top = tk.Toplevel(self)
        top.title("Running processes")
        top.transient(self)
        query = tk.StringVar()
        ttk.Entry(top, textvariable=query).pack(fill="x", padx=8, pady=8)
        lb = tk.Listbox(top, width=40, height=20)
        lb.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        def fill(*a):
            lb.delete(0, "end")
            for n in names:
                if query.get().lower() in n.lower():
                    lb.insert("end", n)
        query.trace_add("write", fill)
        fill()
        def pick(e=None):
            if lb.curselection():
                var.set(lb.get(lb.curselection()[0]))
                top.destroy()
        lb.bind("<Double-Button-1>", pick)
        lb.bind("<Return>", pick)

    def buildButtonEditor(self, parent, n):
        m = self.mode()
        button = m.setdefault("buttons", {}).setdefault(str(n), {"display": {}, "action": {"type": "none"}})
        display = button.setdefault("display", {})

        box = ttk.LabelFrame(parent, text="Key " + str(n) + ": screen", padding=8)
        box.pack(fill="x", pady=(0, 8))
        kind = tk.StringVar(value="icon" if display.get("icon") else ("text" if display.get("text") or display.get("subtext") else "blank"))
        row = ttk.Frame(box)
        row.pack(fill="x")
        body = ttk.Frame(box)
        body.pack(fill="x", pady=(6, 0))

        def flag(parent, label, key, default=False):
            var = tk.BooleanVar(value=display.get(key, default))
            def onFlag(*a):
                if var.get() == default:
                    display.pop(key, None)
                else:
                    display[key] = var.get()
                self.changed()
            var.trace_add("write", onFlag)
            ttk.Checkbutton(parent, text=label, variable=var).pack(side="left", padx=(0, 8))

        def buildBody():
            for w in body.winfo_children():
                w.destroy()
            k = kind.get()
            if k == "icon":
                line = ttk.Frame(body)
                line.pack(fill="x")
                if display.get("icon"):
                    try:
                        photo = toPhoto(self.device.getIcon(display["icon"]), 1)
                        self.editorPhotos.append(photo)
                        tk.Label(line, image=photo, background="white", relief="solid", borderwidth=1).pack(side="left")
                    except OSError:
                        ttk.Label(line, text="(missing)").pack(side="left")
                ttk.Label(line, text=os.path.basename(display.get("icon", "")) or "No icon chosen").pack(side="left", padx=8)
                def setIcon(path):
                    display["icon"] = path
                    buildBody()
                    self.changed()
                ttk.Button(line, text="Choose…", command=lambda: IconPicker(self, setIcon)).pack(side="right")
                flags = ttk.Frame(body)
                flags.pack(fill="x", pady=(6, 0))
                flag(flags, "Centered", "centered", True)
                flag(flags, "Inverted", "inverted")
                flag(flags, "Marked", "marked")
                flag(flags, "Crossed out", "crossed")
            elif k == "text":
                def setText(v):
                    display["text"] = v
                    self.changed()
                self.field(body, "Label:", display.get("text", ""), setText)
                def setSub(v):
                    display["subtext"] = v.replace("\\n", "\n")
                    self.changed()
                self.field(body, "Small text:", display.get("subtext", "").replace("\n", "\\n"), setSub)
                ttk.Label(body, text="Use \\n in the small text for a line break.", foreground="#666").pack(anchor="w")
                flags = ttk.Frame(body)
                flags.pack(fill="x", pady=(4, 0))
                flag(flags, "Inverted", "inverted")

        def setKind(*a):
            k = kind.get()
            keep = {"icon": ("icon", "centered", "inverted", "marked", "crossed"), "text": ("text", "subtext", "inverted"), "blank": ()}[k]
            for key in list(display):
                if key not in keep:
                    del display[key]
            buildBody()
            self.changed()
            if k == "icon" and not display.get("icon"):
                IconPicker(self, lambda path: (display.__setitem__("icon", path), buildBody(), self.changed()))
        for value, label in (("icon", "Icon"), ("text", "Text"), ("blank", "Blank")):
            ttk.Radiobutton(row, text=label, value=value, variable=kind, command=setKind).pack(side="left", padx=(0, 10))
        buildBody()

        box = ttk.LabelFrame(parent, text="Key " + str(n) + ": what it does", padding=8)
        box.pack(fill="x")
        def tapTab(frame):
            ActionEditor(frame, self, lambda: button.get("action"), lambda a: button.__setitem__("action", a)).pack(fill="x")
        self.buildGestureTabs(box, n, button, tapTab)

        if m.get("name") == cm.setting(self.config.get("settings"), "standalone"):
            box = ttk.LabelFrame(parent, text="Key " + str(n) + ": without the controller", padding=8)
            box.pack(fill="x", pady=(8, 0))
            ttk.Label(box, foreground="#666", wraplength=400, justify="left",
                      text="This mode is saved on the keyboard, which uses it when no controller is running. Its own screen then "
                           "shows a text label for each key (3 lines of 8 characters). Leave this empty to describe the tap action.").pack(anchor="w")
            def setLabel(v):
                if v.strip():
                    button["label"] = v
                else:
                    button.pop("label", None)
                self.changed(redraw=False)
                preview.configure(text=cm.fitLabel(button.get("label") or cm.describeAction(button.get("action")), 8, 3).replace("|", "\n"))
            self.field(box, "Label:", button.get("label", ""), setLabel)
            preview = ttk.Label(box, font=("TkFixedFont", 10), text=cm.fitLabel(button.get("label") or cm.describeAction(button.get("action")), 8, 3).replace("|", "\n"))
            preview.pack(anchor="w", pady=(4, 0))

    #The Tap / Hold / Double tap / Combos tabs of a key (or of pressing the dial, key 1)
    def buildGestureTabs(self, parent, key, store, tapTab, allowDouble=True):
        name = "the dial" if key == 1 else "key " + str(key)
        nb = ttk.Notebook(parent)
        nb.pack(fill="x")
        tabs = [("tap", "Tap"), ("long", "Hold")] + ([("double", "Double tap")] if allowDouble else []) + [("combos", "Combos")]
        frames = {}
        for kind, title in tabs:
            frames[kind] = ttk.Frame(nb, padding=8)
            nb.add(frames[kind], text=title)
        note = ttk.Label(parent, foreground="#8a6d00", wraplength=400, justify="left")
        note.pack(fill="x", pady=(6, 0))

        def isSet(kind):
            if kind == "combos":
                return any(cm.isSet(a) for a in (store.get("combos") or {}).values())
            return cm.isSet(store.get(kind))
        def refresh():
            for i, (kind, title) in enumerate(tabs):
                if kind != "tap":
                    nb.tab(i, text=title + ("  \u25cf" if isSet(kind) else ""))
            if key != 1 and (isSet("long") or isSet("double") or isSet("combos")):
                note.configure(text="Because " + name + " has a hold, double-tap or combo action, its tap runs when you let go of it "
                               "(and does not repeat while held).")
            else:
                note.configure(text="")
        self.gestureTabsRefresh = refresh

        tapTab(frames["tap"])
        settings = self.config.get("settings")
        for kind in ("long", "double"):
            if kind not in frames:
                continue
            f = frames[kind]
            if kind == "long":
                text = "Holding " + name + " for " + str(cm.setting(settings, "longPressMs")) + " ms runs this action right away, instead of the tap."
            else:
                text = "Tapping " + name + " twice quickly (within " + str(cm.setting(settings, "doubleTapMs")) + " ms) runs this action. A single tap then waits that long before it runs."
            ttk.Label(f, text=text + " Change the times in Settings.", foreground="#666", wraplength=380, justify="left").pack(anchor="w", pady=(0, 6))
            body = ttk.Frame(f)
            var = tk.BooleanVar(value=isSet(kind))
            def toggle(*a, kind=kind, var=var, body=body):
                for w in body.winfo_children():
                    w.destroy()
                if var.get():
                    if not cm.isSet(store.get(kind)):
                        store[kind] = {"type": "keys", "keys": []}
                    ActionEditor(body, self, lambda: store.get(kind), lambda a: store.__setitem__(kind, a), kind="gesture").pack(fill="x")
                else:
                    store.pop(kind, None)
                refresh()
                self.changed()
            ttk.Checkbutton(f, text={"long": "Do something when held", "double": "Do something when tapped twice"}[kind], variable=var, command=toggle).pack(anchor="w")
            body.pack(fill="x", pady=(4, 0))
            if var.get():
                ActionEditor(body, self, lambda kind=kind: store.get(kind), lambda a, kind=kind: store.__setitem__(kind, a), kind="gesture").pack(fill="x")

        self.buildCombosTab(frames["combos"], key, store, refresh)
        refresh()
        if getattr(self, "gestureTab", 0) < len(tabs):
            nb.select(self.gestureTab)
        nb.bind("<<NotebookTabChanged>>", lambda e: setattr(self, "gestureTab", nb.index("current")))

    def buildCombosTab(self, frame, key, store, refresh):
        name = "the dial" if key == 1 else "key " + str(key)
        ttk.Label(frame, foreground="#666", wraplength=380, justify="left",
                  text="Hold " + name + " and press another key to run a combo. The other key still does its own thing when pressed "
                       "on its own. Pick the other key:").pack(anchor="w", pady=(0, 6))
        combos = store.setdefault("combos", {})
        grid = ttk.Frame(frame)
        grid.pack(fill="x")
        editor = ttk.Frame(frame)
        editor.pack(fill="x", pady=(8, 0))
        others = [k for k in (2, 6, 3, 7, 4, 8, 5, 9, 1) if k != key]
        if getattr(self, "comboPartner", None) not in others:
            self.comboPartner = None

        def label(k):
            a = combos.get(str(k))
            return ("Dial" if k == 1 else str(k)) + ": " + (cm.describeAction(a) if cm.isSet(a) else "\u2014")
        buttons = {}
        def pick(k):
            self.comboPartner = k
            for other, b in buttons.items():
                b.configure(style="Accent.TButton" if other == k else "TButton")
            for w in editor.winfo_children():
                w.destroy()
            if not cm.isSet(combos.get(str(k))):
                combos[str(k)] = {"type": "keys", "keys": []}
            ttk.Label(editor, text="Hold " + name + ", then press " + ("the dial" if k == 1 else "key " + str(k)) + ":",
                      font=("TkDefaultFont", 9, "bold")).pack(anchor="w")
            def setCombo(a, k=k):
                combos[str(k)] = a
                buttons[k].configure(text=label(k))
                refresh()
            ae = ActionEditor(editor, self, lambda: combos.get(str(k)), setCombo, kind="gesture", onType=lambda: buildHint())
            ae.pack(fill="x")
            hint = ttk.Frame(editor)
            hint.pack(fill="x", pady=(8, 0))
            def buildHint():
                for w in hint.winfo_children():
                    w.destroy()
                a = combos.get(str(k)) or {}
                ttk.Label(hint, text="On the screen while " + name + " is held:", font=("TkDefaultFont", 9, "bold")).pack(anchor="w")
                if a.get("type") not in ("open", "command"): #Those have their name field above
                    def setLabel(v):
                        if v.strip():
                            a["label"] = v.strip()
                        else:
                            a.pop("label", None)
                        buttons[k].configure(text=label(k))
                        self.changed()
                    self.field(hint, "Name:", a.get("label", ""), setLabel)
                row = ttk.Frame(hint)
                row.pack(fill="x", pady=(2, 0))
                if a.get("icon"):
                    try:
                        photo = toPhoto(self.device.getIcon(a["icon"]), 1)
                        self.editorPhotos.append(photo)
                        tk.Label(row, image=photo, background="white", relief="solid", borderwidth=1).pack(side="left")
                    except OSError:
                        pass
                def setIcon(path):
                    a["icon"] = path
                    buildHint()
                    self.changed()
                def clearIcon():
                    a.pop("icon", None)
                    buildHint()
                    self.changed()
                ttk.Button(row, text="Choose icon…", command=lambda: IconPicker(self, setIcon)).pack(side="left", padx=(6, 0))
                if a.get("icon"):
                    ttk.Button(row, text="Use the name instead", command=clearIcon).pack(side="left", padx=4)
                ttk.Label(hint, foreground="#666", wraplength=380, justify="left",
                          text="Shows the icon if one is chosen, otherwise the name (or a description of the action).").pack(anchor="w")
            buildHint()
            def remove():
                combos.pop(str(k), None)
                buttons[k].configure(text=label(k), style="TButton")
                self.comboPartner = None
                for w in editor.winfo_children():
                    w.destroy()
                refresh()
                self.changed()
            ttk.Button(editor, text="Remove this combo", command=remove).pack(anchor="w", pady=(6, 0))
            refresh()
            self.changed()
        for i, k in enumerate(others):
            b = ttk.Button(grid, text=label(k), command=lambda k=k: pick(k), width=22)
            b.grid(row=i // 2, column=i % 2, sticky="ew", padx=1, pady=1)
            buttons[k] = b
        if self.comboPartner:
            pick(self.comboPartner)

        #The other direction: combos of other keys that end with this one
        incoming = [(h, a) for h in range(1, 10) if h != key for p, a in cm.gesturesFor(self.mode(), h)["combos"].items() if p == key]
        if incoming:
            ttk.Label(frame, text="Combos that end with " + name + ":", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(10, 2))
            for h, a in incoming:
                row = ttk.Frame(frame)
                row.pack(fill="x")
                ttk.Label(row, text="Hold " + ("the dial" if h == 1 else str(h)) + ", then " + name + ": " + cm.describeAction(a)).pack(side="left")
                def jump(h=h):
                    self.comboPartner = key
                    self.gestureTab = 3 if h != 1 or len(self.mode().get("jog", [])) < 2 else 2
                    self.selectSlot("jog" if h == 1 else h)
                ttk.Button(row, text="Edit", width=5, command=jump).pack(side="right")

    def buildJogEditor(self, parent):
        m = self.mode()
        jog = m.setdefault("jog", [])
        box = ttk.LabelFrame(parent, text="Jog dial functions", padding=8)
        box.pack(fill="x", pady=(0, 8))
        ttk.Label(box, text="Pressing the dial switches between these functions. The label is shown at the bottom of the screen.",
                  foreground="#666", wraplength=400, justify="left").pack(anchor="w", pady=(0, 4))
        lb = tk.Listbox(box, height=max(3, min(6, len(jog))), activestyle="none", exportselection=False, selectbackground=ACCENT)
        lb.pack(fill="x")
        for f in jog:
            lb.insert("end", f.get("label", "") + "   —   " + cm.describeAction(f.get("cw")) + " / " + cm.describeAction(f.get("ccw")))
        if jog:
            self.jogIndex = min(self.jogIndex, len(jog) - 1)
            lb.selection_set(self.jogIndex)
        def onSelect(e):
            if lb.curselection():
                self.jogIndex = lb.curselection()[0]
                self.selectSlot("jog")
        lb.bind("<<ListboxSelect>>", onSelect)

        def add():
            jog.append({"label": "New", "cw": {"type": "none"}, "ccw": {"type": "none"}})
            self.jogIndex = len(jog) - 1
            self.changed()
            self.selectSlot("jog")
        def remove():
            if jog:
                del jog[self.jogIndex]
                self.jogIndex = max(0, self.jogIndex - 1)
                self.changed()
                self.selectSlot("jog")
        def move(d):
            j = self.jogIndex + d
            if 0 <= j < len(jog):
                jog[self.jogIndex], jog[j] = jog[j], jog[self.jogIndex]
                self.jogIndex = j
                self.changed()
                self.selectSlot("jog")
        buttons = ttk.Frame(box)
        buttons.pack(fill="x", pady=(4, 0))
        for text, cmd in (("Add", add), ("Delete", remove), ("Up", lambda: move(-1)), ("Down", lambda: move(1))):
            ttk.Button(buttons, text=text, command=cmd, width=8).pack(side="left", padx=(0, 4))

        if jog:
            f = jog[self.jogIndex]
            box = ttk.LabelFrame(parent, text="Function " + str(self.jogIndex + 1), padding=8)
            box.pack(fill="x", pady=(0, 8))
            def setLabel(v):
                f["label"] = v
                lb.delete(self.jogIndex)
                lb.insert(self.jogIndex, v + "   —   " + cm.describeAction(f.get("cw")) + " / " + cm.describeAction(f.get("ccw")))
                lb.selection_set(self.jogIndex)
                self.changed()
            self.field(box, "Label:", f.get("label", ""), setLabel)
            for direction, title in (("cw", "Turn clockwise (each step):"), ("ccw", "Turn counter-clockwise (each step):")):
                ttk.Label(box, text=title, font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(8, 2))
                ActionEditor(box, self, lambda d=direction: f.get(d), lambda a, d=direction: f.__setitem__(d, a), jog=True).pack(fill="x")

            accel = tk.BooleanVar(value=cm.accelerates(f))
            def setAccel(*a):
                f["accelerate"] = accel.get()
                self.changed(redraw=False)
            ttk.Checkbutton(box, text="Speed up when turned quickly (fast turns count 2\u00d7 or 4\u00d7)", variable=accel, command=setAccel).pack(anchor="w", pady=(8, 0))

            ttk.Label(box, text="Press and turn:", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(10, 2))
            ttk.Label(box, text="Turning while the dial is held down can do something else, like zooming instead of scrolling. "
                                "Turning while pressed never counts as a press of the dial.", foreground="#666", wraplength=400, justify="left").pack(anchor="w")
            pressBody = ttk.Frame(box)
            pressVar = tk.BooleanVar(value=cm.isSet(f.get("pressCw")) or cm.isSet(f.get("pressCcw")))
            def buildPress():
                for w in pressBody.winfo_children():
                    w.destroy()
                if not pressVar.get():
                    return
                for direction, title in (("pressCw", "Pressed and turned clockwise:"), ("pressCcw", "Pressed and turned counter-clockwise:")):
                    ttk.Label(pressBody, text=title).pack(anchor="w", pady=(6, 2))
                    ActionEditor(pressBody, self, lambda d=direction: f.get(d), lambda a, d=direction: f.__setitem__(d, a), jog=True).pack(fill="x")
            def togglePress():
                if pressVar.get():
                    f.setdefault("pressCw", {"type": "none"})
                    f.setdefault("pressCcw", {"type": "none"})
                else:
                    f.pop("pressCw", None)
                    f.pop("pressCcw", None)
                buildPress()
                self.changed()
            ttk.Checkbutton(box, text="Do something else while the dial is pressed", variable=pressVar, command=togglePress).pack(anchor="w", pady=(4, 0))
            pressBody.pack(fill="x")
            buildPress()

            ttk.Label(box, text="LED ring:", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(10, 2))
            volume = tk.BooleanVar(value=f.get("show") == "volume")
            def setVolume(*a):
                if volume.get():
                    f["show"] = "volume"
                else:
                    f.pop("show", None)
                self.changed(redraw=False)
            volume.trace_add("write", setVolume)
            ttk.Checkbutton(box, text="Show the system volume while turning (uses pactl)", variable=volume).pack(anchor="w")
            row = ttk.Frame(box)
            row.pack(fill="x", pady=(4, 0))
            swatch = tk.Label(row, width=3, background=f.get("flash", "#ffffff"), relief="solid", borderwidth=1)
            flashVar = tk.BooleanVar(value=bool(f.get("flash")))
            def setFlash(*a):
                if flashVar.get():
                    f["flash"] = f.get("flash") or "#ff00ff"
                    swatch.configure(background=f["flash"])
                else:
                    f.pop("flash", None)
                self.changed(redraw=False)
            flashVar.trace_add("write", setFlash)
            ttk.Checkbutton(row, text="Flash this color when selected", variable=flashVar).pack(side="left")
            swatch.pack(side="left", padx=6)
            def chooseColor():
                color = colorchooser.askcolor(f.get("flash", "#ff00ff"), parent=self)[1]
                if color:
                    f["flash"] = color
                    flashVar.set(True)
                    swatch.configure(background=color)
                    self.changed(redraw=False)
            ttk.Button(row, text="Color…", command=chooseColor).pack(side="left")

        box = ttk.LabelFrame(parent, text="Pressing the dial", padding=8)
        box.pack(fill="x")
        dial = m.setdefault("dialGestures", {})
        if len(jog) >= 2:
            def tapTab(frame):
                ttk.Label(frame, text="A short press switches to the next dial function. Its name is shown at the bottom of the screen.",
                          foreground="#666", wraplength=380, justify="left").pack(anchor="w")
            self.buildGestureTabs(box, 1, dial, tapTab, allowDouble=False)
        else:
            def tapTab(frame):
                ttk.Label(frame, text="With fewer than two dial functions, pressing the dial works like a key:", foreground="#666").pack(anchor="w", pady=(0, 4))
                ActionEditor(frame, self, lambda: m.get("jogPress"), lambda a: m.__setitem__("jogPress", a)).pack(fill="x")
            self.buildGestureTabs(box, 1, dial, tapTab)

    # ----- Settings and cheat sheet -----

    def showSettings(self):
        settings = self.config.setdefault("settings", {})
        top = tk.Toplevel(self)
        top.title("Settings")
        top.transient(self)
        top.resizable(False, False)
        frame = ttk.Frame(top, padding=14)
        frame.pack(fill="both", expand=True)

        def number(parent, label, name, low, high, step, unit, hint):
            row = ttk.Frame(parent)
            row.pack(fill="x", pady=(6, 0))
            ttk.Label(row, text=label, width=24).pack(side="left")
            var = tk.IntVar(value=int(cm.setting(settings, name)))
            def onChange(*a):
                try:
                    settings[name] = max(low, min(high, int(var.get())))
                except (tk.TclError, ValueError):
                    return
                self.changed(redraw=False)
            var.trace_add("write", onChange)
            ttk.Spinbox(row, from_=low, to=high, increment=step, textvariable=var, width=6).pack(side="left")
            ttk.Label(row, text=unit).pack(side="left", padx=4)
            ttk.Label(parent, text=hint, foreground="#666", wraplength=420, justify="left").pack(anchor="w")

        box = ttk.LabelFrame(frame, text="Keys", padding=10)
        box.pack(fill="x")
        number(box, "Hold for", "longPressMs", 200, 2000, 50, "ms", "How long a key has to be held for its Hold action.")
        number(box, "Double tap within", "doubleTapMs", 150, 800, 25, "ms",
               "How quickly the second tap has to follow. Keys with a double tap wait this long before a single tap runs.")
        hintVar = tk.BooleanVar(value=bool(cm.setting(settings, "comboHints")))
        def setHints():
            settings["comboHints"] = hintVar.get()
            self.changed(redraw=False)
        ttk.Checkbutton(box, text="Show the combos on the screen while their key or the dial is held", variable=hintVar, command=setHints).pack(anchor="w", pady=(8, 0))
        number(box, "Show them after", "comboHintMs", 0, 1500, 50, "ms",
               "Short presses never switch the screen. Each switch takes about a second of e-ink refresh.")

        box = ttk.LabelFrame(frame, text="Without the controller", padding=10)
        box.pack(fill="x", pady=(10, 0))
        ttk.Label(box, text="Mode saved on the keyboard:").pack(anchor="w")
        names = ["(none, F1 to F8)"] + [m.get("name", "") for m in self.config["modes"] if not m.get("python")]
        current = cm.setting(settings, "standalone")
        var = tk.StringVar(value=current if current in names else names[0])
        def setStandalone(e=None):
            settings["standalone"] = None if var.get() == names[0] else var.get()
            self.changed(redraw=False)
            self.selectSlot(self.slot) #Shows or hides the label fields
        box2 = ttk.Combobox(box, textvariable=var, values=names, state="readonly", width=30)
        box2.pack(anchor="w", pady=(2, 0))
        box2.bind("<<ComboboxSelected>>", setStandalone)
        ttk.Label(box, foreground="#666", wraplength=420, justify="left",
                  text="The keyboard starts with this mode when no controller is running, on any computer: its key taps, "
                       "the first dial function and its press-and-turn. Its screen shows a text label per key. The controller "
                       "writes it to the keyboard when it connects and whenever it changes.").pack(anchor="w", pady=(4, 0))

        box = ttk.LabelFrame(frame, text="Screen", padding=10)
        box.pack(fill="x", pady=(10, 0))
        number(box, "Full refresh every", "fullRefreshEvery", 0, 100, 1, "mode switches",
               "A full refresh flashes for a few seconds and keeps the panel healthy in the long run. 0 = never.")

        box = ttk.LabelFrame(frame, text="Notifications", padding=10)
        box.pack(fill="x", pady=(10, 0))
        notifyVar = tk.BooleanVar(value=bool(cm.setting(settings, "notifications")))
        def setNotify():
            settings["notifications"] = notifyVar.get()
            self.changed(redraw=False)
        ttk.Checkbutton(box, text="Show notifications on the LED ring", variable=notifyVar, command=setNotify).pack(anchor="w")
        ttk.Label(box, foreground="#666", wraplength=420, justify="left",
                  text="Programs report events with the inkkeys-notify command. Claude Code is set up to call it: "
                       "green pulse when Claude finishes, amber pulsing when it needs you (until you press a key).").pack(anchor="w", pady=(2, 4))
        row = ttk.Frame(box)
        row.pack(anchor="w")
        import notify
        for event, label in (("done", "Try \u201cdone\u201d"), ("attention", "Try \u201cattention\u201d"), ("clear", "Clear")):
            ttk.Button(row, text=label, command=lambda e=event: notify.notify(e)).pack(side="left", padx=(0, 4))

        ttk.Label(frame, text="Settings are saved with the Save button.", foreground="#666").pack(anchor="w", pady=(10, 0))
        ttk.Button(frame, text="Close", command=top.destroy).pack(anchor="e", pady=(6, 0))
        top.geometry("+%d+%d" % (self.winfo_rootx() + 160, self.winfo_rooty() + 60))

    #Everything the current mode does: one table for the keys, one for the dial functions
    KEY_COLUMNS = (("what", "", 120), ("tap", "Tap", 190), ("hold", "Hold", 190), ("double", "Double tap", 160), ("combos", "Combos (hold this + key)", 250))
    DIAL_COLUMNS = (("what", "Dial function", 120), ("left", "Turn left", 170), ("right", "Turn right", 170), ("pleft", "Pressed + left", 170), ("pright", "Pressed + right", 170), ("fast", "Fast turns", 100))

    def cheatSheetRows(self):
        m = self.mode()
        if m.get("python"):
            return [("", "This mode is defined in modes.py (" + m["python"] + ").", "", "", "")], []
        jog = m.get("jog", [])
        keys = []
        for k in (2, 3, 4, 5, 6, 7, 8, 9, 1):
            g = cm.gesturesFor(m, k)
            if k == 1:
                name = "Dial press"
                tap = "Next dial function" if len(jog) > 1 else cm.describeAction(g["tap"])
            else:
                name = "Key " + str(k) + (" (left)" if k <= 5 else " (right)")
                tap = cm.describeAction(g["tap"])
            combos = "; ".join("+" + ("dial" if p == 1 else str(p)) + ": " + cm.describeAction(a) for p, a in sorted(g["combos"].items()))
            keys.append((name, tap, cm.describeAction(g["long"]) if g["long"] else "", cm.describeAction(g["double"]) if g["double"] else "", combos))
        dial = []
        for f in jog:
            pressed = cm.isSet(f.get("pressCw")) or cm.isSet(f.get("pressCcw"))
            dial.append((f.get("label", ""), cm.describeAction(f.get("ccw")), cm.describeAction(f.get("cw")),
                         cm.describeAction(f.get("pressCcw")) if pressed else "", cm.describeAction(f.get("pressCw")) if pressed else "",
                         "speed up" if cm.accelerates(f) else ""))
        return keys, dial

    def showCheatSheet(self):
        m = self.mode()
        top = tk.Toplevel(self)
        top.title("Cheat sheet: " + m.get("name", ""))
        top.transient(self)
        frame = ttk.Frame(top, padding=10)
        frame.pack(fill="both", expand=True)
        keys, dial = self.cheatSheetRows()
        for title, columns, rows in (("Keys", self.KEY_COLUMNS, keys), ("Dial", self.DIAL_COLUMNS, dial)):
            if not rows:
                continue
            ttk.Label(frame, text=title, font=("TkDefaultFont", 10, "bold")).pack(anchor="w", pady=(4, 2))
            tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", height=len(rows))
            for name, heading, width in columns:
                tree.heading(name, text=heading, anchor="w")
                tree.column(name, width=width, anchor="w")
            for row in rows:
                tree.insert("", "end", values=row)
            tree.pack(fill="x")
        ttk.Label(frame, foreground="#666", text="Keys 2\u20135 are on the left of the screen, 6\u20139 on the right, top to bottom. "
                  "Pressing the dial switches between its functions.").pack(anchor="w", pady=(6, 0))
        def copy():
            text = [m.get("name", "")]
            for title, columns, rows in (("Keys", self.KEY_COLUMNS, keys), ("Dial", self.DIAL_COLUMNS, dial)):
                header = tuple(c[1] or title for c in columns)
                widths = [max(len(str(r[i])) for r in rows + [header]) for i in range(len(columns))]
                text += [""] + [" | ".join(str(v).ljust(widths[i]) for i, v in enumerate(r)).rstrip() for r in [header] + rows]
            self.clipboard_clear()
            self.clipboard_append("\n".join(text))
            self.status.configure(text="Cheat sheet copied")
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(6, 0))
        ttk.Button(buttons, text="Copy as text", command=copy).pack(side="left")
        ttk.Button(buttons, text="Close", command=top.destroy).pack(side="right")

    # ----- Changes, preview and saving -----

    def changed(self, redraw=True):
        if redraw:
            self.drawDevice()
        self.updateTitle()
        self.schedulePreview()

    def updateTitle(self):
        dirty = self.dirty()
        self.title(("* " if dirty else "") + "inkkeys configurator")
        self.status.configure(text="Unsaved changes" if dirty else "")

    def schedulePreview(self):
        if self.previewAfter:
            self.after_cancel(self.previewAfter)
        self.previewAfter = self.after(400, self.writePreview)

    def writePreview(self):
        self.previewAfter = None
        m = self.mode()
        if not self.livePreview.get() or m.get("python"):
            self.removePreview()
            return
        try:
            tmp = cm.PREVIEW_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"mode": m}, f)
            os.replace(tmp, cm.PREVIEW_FILE)
        except OSError:
            pass

    def keepPreviewAlive(self):
        if self.livePreview.get() and os.path.exists(cm.PREVIEW_FILE):
            try:
                os.utime(cm.PREVIEW_FILE)
            except OSError:
                pass
        self.after(2000, self.keepPreviewAlive)

    def removePreview(self):
        try:
            os.remove(cm.PREVIEW_FILE)
        except OSError:
            pass

    def problems(self):
        result = []
        for m in self.config["modes"]:
            if m.get("python"):
                continue
            name = m.get("name", "?")
            for n, b in sorted(m.get("buttons", {}).items()):
                for p in cm.validateAction(b.get("action")):
                    result.append(name + ", key " + n + ": " + p)
            for f in m.get("jog", []):
                for d in ("cw", "ccw"):
                    for p in cm.validateAction(f.get(d), jog=True):
                        result.append(name + ", jog \"" + f.get("label", "") + "\": " + p)
            if m.get("jogPress"):
                for p in cm.validateAction(m["jogPress"]):
                    result.append(name + ", dial press: " + p)
            for k in range(1, 10):
                g = cm.gesturesFor(m, k)
                where = name + (", dial" if k == 1 else ", key " + str(k))
                for kind in ("long", "double"):
                    for p in cm.validateAction(g[kind], jog=True, limit=False):
                        result.append(where + " (" + kind + "): " + p)
                for other, a in g["combos"].items():
                    for p in cm.validateAction(a, jog=True, limit=False):
                        result.append(where + " + " + str(other) + ": " + p)
            for f in m.get("jog", []):
                for d in ("pressCw", "pressCcw"):
                    for p in cm.validateAction(f.get(d), jog=True):
                        result.append(name + ", dial \"" + f.get("label", "") + "\" pressed: " + p)
            match = m.get("match") or {}
            if match.get("type") == "window":
                try:
                    re.compile(match.get("pattern", ""))
                except re.error as e:
                    result.append(name + ": invalid window pattern (" + str(e) + ")")
        return result

    def save(self):
        if self.configMtime() != self.savedMtime and not messagebox.askyesno("Save",
                "layouts.json was changed outside the configurator since you opened it. Overwrite those changes?", parent=self):
            return False
        problems = self.problems()
        if problems and not messagebox.askyesno("Save", "Some actions have problems:\n\n" + "\n".join(problems[:12]) +
                                                "\n\nThe device would cut these short. Save anyway?", parent=self):
            return False
        self.dropEmptyGestures()
        cm.saveConfig(self.config)
        self.savedState = self.normalizedState()
        self.savedMtime = self.configMtime()
        self.updateTitle()
        self.status.configure(text="Saved " + time.strftime("%H:%M:%S") + ", the controller reloads it automatically")
        return True

    def dropEmptyGestures(self, config=None):
        for m in (self.config if config is None else config)["modes"]:
            stores = list((m.get("buttons") or {}).values()) + ([m["dialGestures"]] if "dialGestures" in m else [])
            for store in stores:
                for kind in ("long", "double"):
                    if kind in store and not cm.isSet(store[kind]):
                        del store[kind]
                if "combos" in store:
                    store["combos"] = {k: a for k, a in store["combos"].items() if cm.isSet(a)}
                    if not store["combos"]:
                        del store["combos"]
            if m.get("dialGestures") == {}:
                del m["dialGestures"]
            for f in m.get("jog", []):
                for d in ("pressCw", "pressCcw"):
                    if d in f and not cm.isSet(f[d]):
                        del f[d]

    def revert(self):
        if self.dirty() and messagebox.askyesno("Revert", "Discard all unsaved changes?", parent=self):
            self.config = json.loads(self.savedState)
            self.selectMode(min(self.modeIndex, len(self.config["modes"]) - 1))
            self.updateTitle()

    def onClose(self):
        if self.dirty():
            answer = messagebox.askyesnocancel("Unsaved changes", "Save your changes before closing?", parent=self)
            if answer is None or (answer and not self.save()):
                return
        self.removePreview()
        self.destroy()


if __name__ == "__main__":
    os.chdir(BASE_DIR)
    Configurator().mainloop()
