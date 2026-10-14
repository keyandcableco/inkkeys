SERIALPORT = None  # None = Auto-detect, to specify a specific serial port, you can set it to something like "/dev/ttyACM0" (Linux) or "COM1" (Windows)
VID = 0x2341       # USB Vendor ID for a Pro Micro
PID = 0x8036       # USB Product ID for a Pro Micro
DEBUG = True       # More output on the command line

from inkkeys import *        # Inkkeys module
from processchecks import *  # Functions to check for active processes and windows
try:
    import modes             # Definitions of the hotkey functions in different "modes" that need Python code
except Exception as e:
    print("modes.py could not be loaded (" + str(e) + "), modes that need Python code are not available.")
    modes = None
from configmodes import *    # Modes defined in layouts.json (edit them with configurator.py)
from notify import Notifier  # LED notifications, for example from Claude Code hooks

import os
import sys
import time
from serial import SerialException
import serial.tools.list_ports
import traceback

#Only one controller may talk to the keyboard: two of them answer each other's
#requests and keep losing the connection. A lock file keeps a second one out.
if sys.platform.startswith("linux") or sys.platform == "darwin":
    import fcntl
    lockDir = os.path.join(os.path.expanduser("~"), ".cache", "inkkeys")
    os.makedirs(lockDir, exist_ok=True)
    lockFile = open(os.path.join(lockDir, "controller.lock"), "w")
    try:
        fcntl.flock(lockFile, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("The inkkeys controller is already running (in another terminal?). Only one can use the keyboard at a time.")
        sys.exit(1)

print("https://there.oughta.be/a/macro-keyboard")
print('I will try to stay connected. Press Ctrl+c to quit.')

############################################################################################################

# The modes and when they become active are defined in layouts.json. Edit it with
#     python3 configurator.py
# Changes are picked up automatically while the controller is running.
# Modes that need Python code (like ModeOBS) live in modes.py and are referenced from
# layouts.json with "python": "ModeOBS".

############################################################################################################

# Usually there should not be anything to be customized below this point

############################################################################################################

settings = {}
config = {}

def loadModes(previous):
    global settings, config
    try:
        config = loadConfig()
        settings = config.get("settings", {})
        loaded = buildModes(config, modes)
        print("Loaded " + str(len(loaded)) + " active modes from " + CONFIG_FILE + ": " + ", ".join(i["name"] for i in loaded))
        return loaded
    except FileNotFoundError:
        print(CONFIG_FILE + " not found. Run \"python3 configurator.py\" to create it. Using the built-in fallback mode for now.")
    except Exception as e:
        print("Could not load " + CONFIG_FILE + ": " + str(e))
        if previous:
            print("Keeping the previous modes.")
            return previous
    return [{"mode": ConfigMode({"name": "inkkeys", "title": "inkkeys"}), "name": "Empty", "matches": lambda processes, window: True}]

#Keeps the layout saved on the keyboard (used without the controller) in sync with layouts.json
def syncStandalone():
    if device.version < 2:
        return
    name = setting(settings, "standalone")
    spec = next((m for m in config.get("modes", []) if m.get("name") == name and not m.get("python")), None)
    if spec is None:
        if device.savedChecksum:
            print("No standalone mode chosen, removing the layout saved on the keyboard.")
            device.eraseLayout()
        return
    slots, labels, checksum = standaloneLayout(spec)
    if checksum != device.savedChecksum:
        print("Saving \"" + name + "\" on the keyboard, for use without the controller.")
        if not device.saveLayout(slots, labels, checksum):
            print("Saving the layout on the keyboard did not complete.")

def applySettings():
    device.fullRefreshEvery = int(setting(settings, "fullRefreshEvery"))
    notifier.enabled = bool(setting(settings, "notifications"))

def configMtime():
    try:
        return os.path.getmtime(CONFIG_FILE)
    except OSError:
        return None

activeModes = loadModes(None)
activeModesMtime = configMtime()

def work():
    global activeModes, activeModesMtime
    mode = None
    pollInterval = 0
    lastPoll = 0
    lastProcessList = 0
    lastModeCheck = 0
    lastConfigCheck = 0
    processes = set()
    activeWindow = None
    previewSpec = None   #Mode shown while the configurator is open
    previewMode = None
    shownName = None     #Name of the mode on the device, so edits in the preview do not count as mode switches
    applySettings()
    syncStandalone()

    try:
        while True:
            now = time.time()

            if now - lastConfigCheck > 1.0:
                mtime = configMtime()
                if mtime != activeModesMtime:
                    activeModesMtime = mtime
                    activeModes = loadModes(activeModes)
                    applySettings()
                    syncStandalone()
                    if mode is not None:
                        mode.deactivate(device)
                    mode = None
                    lastModeCheck = 0 #Pick the matching mode right away
                lastConfigCheck = now

            if now - lastProcessList > 5.0:
                processes = getActiveProcesses()
                lastProcessList = now

            if now - lastModeCheck > 0.5:
                window = getActiveWindow()
                if window is not None and window != activeWindow:
                    activeWindow = window
                    if DEBUG:
                        print("Active window: " + str(activeWindow))

                spec = readPreview()
                if spec != previewSpec:
                    previewSpec = spec
                    previewMode = ConfigMode(spec, settings) if spec and not spec.get("python") else None
                    if mode is not None:
                        mode.deactivate(device)
                    mode = None

                candidates = [{"mode": previewMode, "name": "Preview of " + previewSpec.get("name", ""), "key": previewSpec.get("name", ""), "matches": lambda processes, window: True}] if previewMode else activeModes
                for i in candidates:
                    if i["matches"](processes, activeWindow):
                        if i["mode"] != mode:
                            if mode is not None:
                                mode.deactivate(device)
                            mode = i["mode"]
                            if DEBUG:
                                print("Mode: " + i["name"])
                            if i.get("key", i["name"]) != shownName:
                                device.modeSwitch()
                                shownName = i.get("key", i["name"])
                            mode.activate(device)
                            pollInterval = 0
                        break
                lastModeCheck = now

            if mode is not None:
                if pollInterval is not False and pollInterval >= 0 and now - lastPoll > pollInterval:
                    pollInterval = mode.poll(device)
                    lastPoll = now

                # Fast loop functions
                mode.animate(device)
            notifier.animate(device)
            device.poll()

            # Limit to ~30fps
            timeTo30fps = now + 0.0333 - time.time()
            if timeTo30fps > 0:
                time.sleep(timeTo30fps)

    except KeyboardInterrupt:
        print('Disconnected from device. Hit Ctrl+c again to quit before reconnect.')


def tryUsingPort(port):
    try:
        if device.connect(port):
            work()
            device.disconnect()
            return True
    except SerialException as e:
        print("Serial error: ", e)
    except:
        if DEBUG:
            print(traceback.format_exc())
        print("Error: ", sys.exc_info()[0])
    return False


# Instantiate the device
device = Device()
device.debug = DEBUG
notifier = Notifier()
device.listeners.append(notifier.onDeviceLine)

try:
    while True:
        if SERIALPORT is not None:
            tryUsingPort(SERIALPORT)
        else:
            for port in serial.tools.list_ports.comports():
                if port.vid != VID or port.pid != PID:
                    continue
                if tryUsingPort(port.device):
                    break
        print("I will retry in three seconds...")
        time.sleep(3)

except KeyboardInterrupt:
    print('Ok, bye.')
