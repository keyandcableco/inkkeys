//Structure to hold events to be assigned to keys
typedef struct {
  byte deviceAndType; //Defines the device in the lower nibble (mouse, keyboard, consumer, delay) and the type in the higher nibble (key press, key release, increment by value, key stroke (press and release)), see definitions below
  unsigned short keycodeOrDelay; //For regular devices, this is the keycode, for mice the higher byte is the button, axis or wheel and the lower is the increment value as signed int8, for delays this is the time in ms
} Event;

// Compare to Event.deviceAndType & 0x0f
const byte DEVICE_NONE = 0x00; //No event
const byte DEVICE_DELAY = 0x01;
const byte DEVICE_CONSUMER = 0x02;
const byte DEVICE_KEYBOARD = 0x03;
const byte DEVICE_MOUSE = 0x04;

// Compare to Event.deviceAndType & 0xf0
const byte TYPE_NONE = 0x00;
const byte TYPE_PRESS = 0x10;
const byte TYPE_RELEASE = 0x20;
const byte TYPE_INCREMENT = 0x30;
const byte TYPE_STROKE = 0x40;

// Compare to Event.keycodeOrDelay & 0xff00
const byte MOUSEAXIS_BUTTON = 0x00; //The button is defined in second byte using the definitions in BootMouse
const byte MOUSEAXIS_X = 0x01;
const byte MOUSEAXIS_Y = 0x02;
const byte MOUSEAXIS_WHEEL = 0x03;

const byte N_EVENTS = 10; //Maximum Number of events
const byte N_SLOTS = 11;  //Keys 1-9, turning the jog dial, turning the jog dial while it is pressed
//Array holding the current assignments, keys 1-9 at indices 0-8, then rotary at index 9 and rotary while
//the dial is pressed at index 10. Second index is press (0) or release (1) or + (0) or - (1) for rotary.
//Third index is sequence of events up to N_EVENTS
Event assignments[N_SLOTS][2][N_EVENTS];
