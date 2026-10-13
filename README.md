# inkkeys
Details and instructions can be found on https://there.oughta.be/a/macro-keyboard

In contrast to most of my other projects, I decided to put this into its own repository as it is slightly more complex and I am hoping for community contributions.

If you have pull-requests, bug reports or want to contribute new case designs, please do not hesitate to open an issue. For generic discussions, "show and tell" and if you are looking for support for something that is not a problem in the code here, I would recommend [r/thereoughtabe on reddit](https://www.reddit.com/r/thereoughtabe/).

<a href="https://www.buymeacoffee.com/there.oughta.be" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-blue.png" alt="Buy Me A Coffee" height="47" width="174" ></a>

## About this fork

This fork of [Staacks/inkkeys](https://github.com/Staacks/inkkeys) keeps the hardware as it is and adds:

* **A graphical configurator** instead of editing Python: click a key on a picture of the device, pick an icon, record a key combination. Modes live in `python-controller/layouts.json`, and the controller reloads them as soon as you save.
* **Hold, double tap and combos** on every key and on the dial, plus actions that **type text**, **open a website** or **run a command** (launch apps).
* **Combos on the screen**: while a key or the dial with combos is held, the screen shows what each combo does.
* **Press and turn**: turning the dial while it is pressed does something else, and fast turns speed up.
* **A layout saved on the keyboard**, so it works on any computer without the controller, and draws its own key labels.
* **LED notifications**, for example from Claude Code hooks (green when it is done, amber when it needs you).
* **Clean partial refreshes on revision 2 displays**, which left grey ghosts with the original code ([#16](https://github.com/Staacks/inkkeys/issues/16), [#23](https://github.com/Staacks/inkkeys/pull/23)).

![The configurator](img/configurator.png?raw=true "Editing a mode in the configurator. Keys 2 and 3 are highlighted because they combine with the dial.")

### Setup

1. Flash `arduino/inkkeys` (libraries: HID-Project, Encoder, GxEPD2, Adafruit NeoPixel). In `settings.h`, set `DISPLAY_REVISION` to 2 if you have the newer display (and swap the pins as described [below](#display-revision-2)), and pick the `LED_TYPE` of your LEDs.
2. Install the Python packages: `pip3 install pyserial pillow psutil python-xlib` (on Linux; `pywin32` on Windows, `pyobjc` on macOS). The configurator also needs Tkinter (`python3-tk` on Debian/Ubuntu).
3. Run `python3 python-controller/controller.py` and, to change things, `python3 python-controller/configurator.py`.

The configurator and the window detection are developed on Linux (X11). Window detection has code for Windows and macOS, but they are untested.

## Setting up the keys (configurator)

Click a key, the screen or the jog dial on the picture of the device to edit it. Key combinations can be recorded by pressing them, icons are picked from a searchable list, and each mode can be bound to a window (with a "Detect" button) or a running process. The first enabled mode in the list that matches wins, so keep the fallback mode at the bottom. While the configurator is open, the keyboard shows the mode you are editing, including unsaved changes.

Modes that need Python code (like the OBS integration) still live in `modes.py` and appear in the list as Python modes, so you can still choose when they are active. "Import…" in the configurator (or `python3 configmodes.py --import`) converts classes from `modes.py` into editable modes.

### What a key can do

Each key has four tabs in the configurator. A dot on a tab shows that it is used.

* **Tap**: the normal action. Key combinations are held while the key is held, like on a normal keyboard. Besides keys, media keys, mouse buttons and mouse movement, a key can **type text** (a snippet, a signature, a prompt), **open a website or file**, or **run a command** (installed Chrome web apps start with `google-chrome --app-id=...`).
* **Hold**: a different action when the key is held down (450 ms by default).
* **Double tap**: a different action when the key is tapped twice quickly (within 300 ms by default).
* **Combos**: hold this key and press another one. The other key still does its own thing when pressed alone, so a key with combos works like a Shift key for a few others. Hold the dial and press a key for a second layer of shortcuts in every mode.

Keys with a hold, double tap or combo run their tap when you let go (otherwise the keyboard cannot know which one you meant), all other keys react instantly. In the configurator, the key caps show badges for these, and selecting a key highlights the keys it combines with (blue: hold the selected key and press these; amber: these keys combine with the selected one). "Cheat sheet for this mode…" lists everything in one table.

On the device, holding a key (or the dial) with combos for a moment switches the screen to show what each combo does: a name or an icon per combo, set in the combo editor. Letting go switches back. Each switch is an e-ink refresh of about a second, so short presses never trigger it.

The dial can do something else while it is pressed and turned ("Press and turn"), and speeds up when turned quickly. Hold times, the double tap window and the other settings are under "Settings…".

### Without the controller

The mode chosen under "Settings…" is saved on the keyboard itself (EEPROM). The keyboard starts with it when no controller is running, on any computer: the key taps, the first dial function and its press-and-turn work, and the keyboard draws a text label for each key on its own screen with a small built-in font. Holds, double taps, combos, typing text and launching need the controller.

### LED notifications

`python-controller/inkkeys-notify done` makes the LED ring pulse green, `inkkeys-notify attention` pulses amber until a key is pressed, `inkkeys-notify clear` stops it. To use it with Claude Code, copy the script somewhere on your PATH and add hooks to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "Stop": [{"hooks": [{"type": "command", "command": "inkkeys-notify done"}]}],
    "Notification": [{"hooks": [{"type": "command", "command": "inkkeys-notify attention"}]}],
    "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "inkkeys-notify clear"}]}]
  }
}
```

### Firmware notes

* Version 2 of the serial protocol (reported by `I`) adds: `X <events>` runs events right away, `T <text>` types text (`\n` is Enter), `O A 1` turns on dial acceleration, `A P+ <events>` / `A P- <events>` assign turning while the dial is pressed, `E ...` saves a layout in the EEPROM (see `standalone.ino`), and `G <slot>` prints an assignment. The controller still works with older firmware, without the new features.
* Image rows are written in chunks and serial input is read a packet at a time, which makes screen updates much faster than writing row by row.
* Typing text through the keyboard can get scrambled in old X11 programs that talk to an input method through XIM (like xterm, or Tk programs with IBus). GTK, Qt, Chrome and Electron programs are fine.

## Common problems

### Display revision 2
Apparently, the original design used revision 1 of the display, while many newly ordered version are revision 2. There are a few differences and thankfully, [Corky402 made a good list of required changes on Reddit](https://www.reddit.com/r/arduino/comments/l4wxxf/the_hardware_is_assembled_and_passed_all_tests/gqovq1j?utm_source=share&utm_medium=web2x&context=3). Here is an excerpt of the original post for reference:
>If you want to test your display hooked to a Arduino or Raspberry Pi you need to run examples for the epd2in9_V2 not the epd2in9.
>
>To get this awesome project working there is no need to make any alterations to the PCB, just simply plumb the Waveshare up on the connectors as I describe, not as per Sebastian's original post.
>
>PCB Pin Waveshare wiring loom
>
>+5v Grey
>
>GND Brown
>
>DIN Blue
>
>CLK Yellow
>
>CS Orange
>
>DC Green
>
>RST Purple
>
>BUSY White
>
>In short you are swapping the RST & BUSY lines on the PCB.
>
>Next, go to your Arduino sketch. This is for the hardware-test script. Enable line numbering and go to line 43 which reads -
>
```c
GxEPD2_290 display(/*CS=*/ PIN_CS, /*DC=*/ PIN_DC, /*RST=*/ PIN_RST, /*BUSY=*/ PIN_BUSY);
```
>
>Change this to -

```c
GxEPD2_290_T94 display(/*CS=*/ PIN_CS, /*DC=*/ PIN_DC, /*RST=*/ PIN_RST, /*BUSY=*/ PIN_BUSY);
```

>Then go to settings.h
>
>Lines 2 - 7 need to be altered so change that section of code as follows -
```c
const byte PIN_DIN = 16;
const byte PIN_CLK = 15;
const byte PIN_CS = 19;
const byte PIN_DC = 18;
const byte PIN_RST = 10;
const byte PIN_BUSY = 14;
```
>
>The sketch will then compile and when uploaded to the board you will get the Waveshare drawing all sorts of Austin Powers time machine circles that make your eyes spin! 

The class change above applies to the hardware test. In the main inkkeys sketch, set `#define DISPLAY_REVISION 2` in `settings.h` instead (and swap the RST and BUSY pins there as shown above). This selects `GxEPD2_290_T94_V2` together with a partial refresh waveform tuned for this panel. With the stock waveform, partial refreshes on revision 2 leave grey ghosts of previous images and unchanged black areas fade (see [#16](https://github.com/Staacks/inkkeys/issues/16)).

If partial refreshes on your display still look grey, or smear the edges of icons, adjust `PARTIAL_REFRESH_REPEATS` in `settings.h` (3 by default, more drives harder but takes ~0.25s longer per step). You can try values without flashing by sending `R p <repeats>` over the serial connection instead of `R p`.


## Gallery

![Original design](img/original.jpg?raw=true "Original design as presented on there.oughta.be with the 3d printing files from this repository.")
Original design as presented on there.oughta.be with the 3d printing files from this repository.

![Original design](img/john_mat_roland.jpg?raw=true "Design by John, Mat and Roland from the UK. The case was CNC milled from beech with a similarly machined clear perspex lid.")
Design by John, Mat and Roland from the UK. The case was CNC milled from beech with a similarly machined clear perspex lid. You can find the knob with finger dimple by Roland Irving in the 3dprint folder as know_with_dimple.stl.

