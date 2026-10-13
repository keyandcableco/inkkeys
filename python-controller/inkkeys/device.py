from .protocol import *
import os
import serial
import time
from collections import deque
from threading import RLock
from PIL import Image, ImageDraw, ImageOps, ImageFont

#The python-controller folder. Relative font and icon paths are resolved against it,
#so the controller works no matter which directory it is started from.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def resolvePath(path):
    if os.path.isabs(path) or os.path.exists(path):
        return path
    return os.path.join(BASE_DIR, path)

#Pillow 10 removed font.getsize(). Use it where it exists, so text renders
#pixel-identical on older Pillow versions, and fall back to the bounding box otherwise.
def textSize(font, text):
    if hasattr(font, "getsize"):
        return font.getsize(text)
    left, top, right, bottom = font.getbbox(text)
    return right, bottom

def multilineTextSize(font, text):
    if hasattr(font, "getsize_multiline"):
        return font.getsize_multiline(text)
    left, top, right, bottom = ImageDraw.Draw(Image.new("1", (1, 1))).multiline_textbbox((0, 0), text, font=font)
    return right, bottom

class Device:
    ser = None
    inbuffer = ""

    awaitingResponseLock = RLock()

    testmode = False
    nLeds = 0
    dispW = 128 #Defaults allow rendering previews without a device, they are replaced by the values reported by the device
    dispH = 296
    rotFactor = 0
    rotCircleSteps = 0
    version = 1         #Firmware version 2 adds running events, typing text, options and saved layouts
    savedChecksum = 0   #Checksum of the layout saved on the keyboard, 0 if there is none

    bannerHeight = 12 #Defines the height of top and bottom banner

    #Partial refreshes leave faint traces that add up. A full refresh (which flashes for ~4s)
    #clears them, so one is done on every n-th mode switch. 0 disables this.
    fullRefreshEvery = 20

    callbacks = {} #This object stores callback functions that react directly to a keypress reported via serial

    ledState = None         #Current LED status, so we can animate them over time
    ledTime = None          #Last time LEDs were set

    debug = False;

    def __init__(self):
        self.callbacks = {}
        self.listeners = [] #Functions called with every line from the device (key presses, turns...)
        self.fonts = {}
        self.icons = {}
        self.resetScreenState()

    #The display controller keeps two buffers: "current" (what the next refresh shows) and
    #"previous" (what is on the panel now). A partial refresh only drives pixels that differ
    #between them. After each refresh, every changed tile is sent a second time (flagged
    #with "a") so the device writes it to both buffers.
    def resetScreenState(self):
        self.onScreen = {}  #Rectangle (x, y, w, h) -> bytes currently shown in that area
        self.pending = {}   #Rectangle -> bytes sent since the last refresh
        self.lineQueue = deque() #Lines that arrived while waiting for a response, handled by poll()
        self.assigned = {}  #Key -> event sequence the device has now, so unchanged assignments are not sent again
        self.options = {}   #Option -> value last sent
        self.ledOverride = False #Set while a notification animates the LEDs, modes cannot change them then
        self.modeSwitches = 0
        self.cleanOnNextUpdate = False

    #Called by the controller when a different mode becomes active
    def modeSwitch(self):
        if self.fullRefreshEvery > 0:
            self.modeSwitches += 1
            if self.modeSwitches >= self.fullRefreshEvery:
                self.cleanOnNextUpdate = True

    def connect(self, dev):
        print("Connecting to ", dev, ".")
        self.ser = serial.Serial(dev, 115200, timeout=1)
        self.inbuffer = ""
        self.resetScreenState()
        self.version = 1
        self.savedChecksum = 0
        if not self.requestInfo(3):
            self.disconnect()
            return False
        if self.testmode:
            print("Connection to ", self.ser.name, " was successfull, but the device is running the hardware test firmware, which cannot be used for anything but testing. Please flash the proper inkkeys firmware to use it.")
            return False
        print("Connected to ", self.ser.name, ".")
        return True

    def disconnect(self):
        if self.ser != None:
            self.ser.close()
            self.ser = None

    def sendToDevice(self, command):
        if self.debug:
            print("Sending: " + command)
        self.ser.write((command + "\n").encode())

    def sendBinaryToDevice(self, data):
        if self.debug:
            print("Sending " + str(len(data)) + " bytes of binary data.")
        self.ser.write(data)

    def readFromDevice(self):
        if self.ser.in_waiting > 0:
            self.inbuffer += self.ser.read(self.ser.in_waiting).decode(errors="replace").replace("\r", "")
        chunks = self.inbuffer.split("\n", 1)
        if len(chunks) > 1:
            cmd = chunks[0]
            self.inbuffer = chunks[1]
            if self.debug:
                print("Received: " + cmd)
            return cmd
        return None

    #Reads lines until one equals "expected". Other lines (like key presses that
    #happen during a display refresh) are queued for poll() instead of being lost.
    def waitForLine(self, expected, timeout):
        start = time.time()
        while time.time() - start < timeout:
            line = self.readFromDevice()
            if line == None:
                time.sleep(0.005)
            elif line == expected:
                return True
            elif line != "":
                self.lineQueue.append(line)
        print("Timeout while waiting for \"" + expected + "\" from the device.")
        return False

    #Handles everything the device sent since the last call
    def poll(self):
        while True:
            with self.awaitingResponseLock:
                input = self.lineQueue.popleft() if self.lineQueue else self.readFromDevice()
            if input is None:
                return
            if not input:
                continue
            for listener in list(self.listeners):
                listener(input)
            if input[0] == KeyCode.JOG.value and (input[1:].isdecimal() or (input[1:2] == '-' and input[2:].isdecimal())):
                if KeyCode.JOG.value in self.callbacks:
                    self.callbacks[KeyCode.JOG.value](int(input[1:]))
            elif input in self.callbacks:
                self.callbacks[input]()

    def registerCallback(self, cb, key):
        self.callbacks[key.value] = cb

    def clearCallback(self, key):
        if key.value in self.callbacks:
            del self.callbacks[key.value]

    def clearCallbacks(self):
        self.callbacks = {}

    def assignKey(self, key, sequence):
        if self.assigned.get(key.value) == list(sequence):
            return
        self.assigned[key.value] = list(sequence)
        self.sendToDevice(CommandCode.ASSIGN.value + " " + key.value + (" " + " ".join(sequence) if len(sequence) > 0 else ""))

    def sendLed(self, colors):
        #Not printed in debug mode: animations send up to 30 of these per second
        self.ser.write((CommandCode.LED.value + " " + " ".join(colors) + "\n").encode())

    #Runs events right away (firmware version 2). Long sequences are split, the firmware takes 10 at a time.
    def execute(self, events):
        events = list(events)
        for i in range(0, len(events), 10):
            self.sendToDevice(CommandCode.EXECUTE.value + " " + " ".join(events[i:i+10]))

    #Types text through the keyboard (firmware version 2). Only ASCII can be typed, other characters are skipped.
    def typeText(self, text):
        text = "".join(c for c in text if c == "\n" or 32 <= ord(c) < 127)
        escaped = text.replace("\\", "\\\\").replace("\n", "\\n")
        chunk = 200
        i = 0
        while i < len(escaped):
            part = escaped[i:i+chunk]
            if (len(part) - len(part.rstrip("\\"))) % 2:
                part = part[:-1] #Do not split an escape sequence
            self.sendToDevice(CommandCode.TYPE.value + " " + part)
            i += len(part)

    def setOption(self, name, value):
        if self.version < 2 or self.options.get(name) == value:
            return
        self.options[name] = value
        self.sendToDevice(CommandCode.OPTION.value + " " + name + " " + str(value))

    #Saves a layout on the keyboard, used when it starts without the controller (firmware version 2).
    #slots: {"2p": [events], ..., "R+": [...], "P-": [...]}, labels: 10 strings (title, dial, keys 2-9)
    def saveLayout(self, slots, labels, checksum):
        with self.awaitingResponseLock:
            self.sendToDevice(CommandCode.STORE.value + " X")
            for slot, events in slots.items():
                self.sendToDevice((CommandCode.STORE.value + " A " + slot + " " + " ".join(events[:10])).rstrip())
            for i, label in enumerate(labels[:10]):
                self.sendToDevice(CommandCode.STORE.value + " L " + str(i) + " " + label)
            self.sendToDevice(CommandCode.STORE.value + " C " + str(checksum))
            if self.waitForLine("ok", 10):
                self.savedChecksum = checksum
                return True
            return False

    def eraseLayout(self):
        self.sendToDevice(CommandCode.STORE.value + " X")
        self.savedChecksum = 0

    def requestInfo(self, timeout):
        with self.awaitingResponseLock:
            print("Requesting device info...")
            start = time.time()
            self.sendToDevice(CommandCode.INFO.value)
            line = self.readFromDevice()
            while line != "Inkkeys":
                if time.time() - start > timeout:
                    return False
                if line == None:
                    time.sleep(0.1)
                    line = self.readFromDevice()
                    continue
                print("Skipping: ", line)
                line = self.readFromDevice()
            print("Header found. Waiting for infos...")
            line = self.readFromDevice()
            while line != "Done":
                if time.time() - start > timeout:
                    return False
                if line == None:
                    time.sleep(0.1)
                    line = self.readFromDevice()
                    continue
                if line.startswith("TEST "):
                    self.testmode = line[5] != "0"
                elif line.startswith("N_LED "):
                    self.nLeds = int(line[6:])
                elif line.startswith("DISP_W "):
                    self.dispW = int(line[7:])
                elif line.startswith("DISP_H "):
                    self.dispH = int(line[7:])
                elif line.startswith("ROT_CIRCLE_STEPS "):
                    self.rotCircleSteps = int(line[17:])
                elif line.startswith("VERSION "):
                    self.version = int(line[8:])
                elif line.startswith("SAVED "):
                    self.savedChecksum = int(line[6:])
                else:
                    print("Skipping: ", line)
                line = self.readFromDevice()
            print("End of info received.")
            print("Testmode: ", self.testmode)
            print("Number of LEDs: ", self.nLeds)
            print("Display width: ", self.dispW)
            print("Display height: ", self.dispH)
            print("Rotation circle steps: ", self.rotCircleSteps)
            print("Firmware version: ", self.version)
            return True

    def _sendImageData(self, rect, data, again=False):
        x, y, w, h = rect
        self.sendToDevice(CommandCode.DISPLAY.value + " " + str(x) + " " + str(y) + " " + str(w) + " " + str(h) + (" a" if again else ""))
        self.sendBinaryToDevice(data)

    def sendImage(self, x, y, image):
        w, h = image.size
        rect = (x, y, w, h)
        data = image.convert("1").rotate(180).tobytes()
        with self.awaitingResponseLock:
            if rect not in self.pending and self.onScreen.get(rect) == data:
                return True #Already on the screen, nothing to do
            #Anything partially covered by this image is no longer known
            for other in [r for r in self.onScreen if r != rect and self._overlaps(r, rect)]:
                del self.onScreen[other]
            self.pending[rect] = data
            self._sendImageData(rect, data)
        return True

    @staticmethod
    def _overlaps(a, b):
        return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]

    #Shows everything sent since the last update. If nothing changed, the refresh
    #is skipped entirely (unless a full refresh is requested to clear ghosting).
    def updateDisplay(self, fullRefresh=False, timeout=6):
        with self.awaitingResponseLock:
            if not self.pending and not fullRefresh:
                return True
            if self.cleanOnNextUpdate or fullRefresh:
                fullRefresh = True
                self.cleanOnNextUpdate = False
                self.modeSwitches = 0
            line = self.readFromDevice() #Drop a late "ok" from an earlier timeout, keep everything else
            while line != None:
                if line != "ok" and line != "":
                    self.lineQueue.append(line)
                line = self.readFromDevice()
            self.sendToDevice(CommandCode.REFRESH.value + " " + (RefreshTypeCode.FULL.value if fullRefresh else RefreshTypeCode.PARTIAL.value))
            if not self.waitForLine("ok", timeout):
                return False
            for rect, data in self.pending.items():
                self._sendImageData(rect, data, again=True)
                self.onScreen[rect] = data
            self.pending = {}
            self.sendToDevice(CommandCode.REFRESH.value + " " + RefreshTypeCode.OFF.value)
            return self.waitForLine("ok", timeout)

    def getAreaFor(self, function):
        if function == "title":
            return (0, self.dispH-self.bannerHeight, self.dispW, self.bannerHeight)
        elif function == 1:
            return (0, 0, self.dispW, self.bannerHeight)
        elif function <= 5:
            return (self.dispW//2, (5-function)*self.dispH//4+self.bannerHeight, self.dispW//2, self.dispH//4-2*self.bannerHeight)
        else:
            return (0, (9-function)*self.dispH//4+self.bannerHeight, self.dispW//2, self.dispH//4-2*self.bannerHeight)

    def getFont(self, name):
        if name not in self.fonts:
            self.fonts[name] = ImageFont.truetype(resolvePath(os.path.join("font", name)), 10)
        return self.fonts[name]

    def getIcon(self, path):
        path = resolvePath(path)
        if path not in self.icons:
            self.icons[path] = Image.open(path).convert("RGB")
        return self.icons[path]

    def sendImageFor(self, function, image):
        x, y, w, h = self.getAreaFor(function)
        if (w, h) != image.size:
            if self.debug:
                print("Rescaling image from " + str(image.size) + " to " + str((w, h)) + ".")
            image = image.resize((w, h))
        self.sendImage(x, y, image)

    #Renders the label for a function without sending it (also used by the configurator preview)
    def renderTextFor(self, function, text, subtext="", inverted=False):
        x, y, w, h = self.getAreaFor(function)
        img = Image.new("1", (w, h), color=(0 if inverted else 1))
        d = ImageDraw.Draw(img)
        font1 = self.getFont("Munro.ttf")
        wt1, ht1 = textSize(font1, text)
        font2 = self.getFont("MunroSmall.ttf")
        wt2, ht2 = multilineTextSize(font2, subtext)
        if function == 1 or function == "title":
            position1 = ((w-wt1)/2,(h-ht1-(0.5 if function == "title" else 0))/2) #Center jog wheel and title label (the title get's small -0.5 nudge for rounding to prefer a top alignment)
            position2 = None
        elif function < 6:
            d.line([(0, h/2), (wt1, h/2)], fill=(1 if inverted else 0))
            position1 = (0,h/2-ht1-2) #Align left
            position2 = (0,h/2-1)
            align="left"
        else:
            d.line([(w, h/2), (w-wt1, h/2)], fill=(1 if inverted else 0))
            position1 = (w-wt1,h/2-ht1-2) #Align right
            position2 = (w-wt2,h/2-1)
            align="right"
        d.text(position1, text, font=font1, fill=(1 if inverted else 0))
        if position2 != None and subtext != None:
            d.multiline_text(position2, subtext, font=font2, align=align, spacing=-2, fill=(1 if inverted else 0))
        return img

    def sendTextFor(self, function, text, subtext="", inverted=False):
        self.sendImageFor(function, self.renderTextFor(function, text, subtext, inverted))

    #Renders an icon for a function without sending it (also used by the configurator preview)
    def renderIconFor(self, function, icon, inverted=False, centered=True, marked=False, crossed=False):
        x, y, w, h = self.getAreaFor(function)
        img = Image.new("1", (w, h), color=(0 if inverted else 1))
        imgIcon = self.getIcon(icon)
        if inverted:
            imgIcon = ImageOps.invert(imgIcon)
        wi, hi = imgIcon.size
        if function < 6:
            pos = ((w-wi)//2 if centered else 0, (h - hi)//2)
        else:
            pos = ((w-wi)//2 if centered else (w - wi), (h - hi)//2)
        img.paste(imgIcon, pos)

        if marked:
            imgMarker = self.getIcon("icons/chevron-compact-right.png" if function < 6 else "icons/chevron-compact-left.png")
            wm, hm = imgMarker.size
            img.paste(imgMarker, (-16,(h - hm)//2) if function < 6 else (w-wm+16,(h - hm)//2), mask=ImageOps.invert(imgMarker).convert("1"))

        if crossed:
            d = ImageDraw.Draw(img)
            d.line([pos[0]+5, pos[1]+5, pos[0]+wi-5, pos[1]+hi-5], width=3)
            d.line([pos[0]+5, pos[1]+hi-5, pos[0]+wi-5, pos[1]+5], width=3)

        return img

    def sendIconFor(self, function, icon, inverted=False, centered=True, marked=False, crossed=False):
        x, y, w, h = self.getAreaFor(function)
        self.sendImage(x, y, self.renderIconFor(function, icon, inverted, centered, marked, crossed))

    def setLeds(self, leds):
        if self.ledOverride:
            return
        ledStr = ['{:06x}'.format(i) for i in leds]
        self.ledTime = time.time()
        self.ledState = leds
        self.sendLed(ledStr)

    def fadeLeds(self):
        if self.ledState == None or self.ledOverride:
            return
        p = (3.5 - (time.time() - self.ledTime))/0.5 #Stay on for 3 seconds and then fade out over 0.5 seconds
        if p >= 1:
            return
        if p <= 0:
            self.ledState = None
            self.sendLed(["000000" for i in range(self.nLeds)])
            return
        dimmedLeds = [(int((i & 0xff0000) * p) & 0xff0000) | (int((i & 0xff00) * p) & 0xff00) | (int((i & 0xff) * p) & 0xff) for i in self.ledState]
        ledStr = ['{:06x}'.format(i) for i in dimmedLeds]
        self.sendLed(ledStr)
