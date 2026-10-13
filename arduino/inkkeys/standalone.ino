/*
 * E-Ink adaptive macro keyboard
 * See https://there.oughta.be/a/macro-keyboard
 *
 * A layout saved on the keyboard (EEPROM), used when it starts. With it, the keyboard
 * works on any computer, without the controller. The controller stores it with "E"
 * commands, and at boot the keys get its assignments and the screen shows its labels.
 */

#include <EEPROM.h>
#include "labels.h"

const uint16_t EE_MAGIC = 0x4B49;   //"IK"
const byte EE_VERSION = 1;
const int EE_ADDR_MAGIC = 0;
const int EE_ADDR_VERSION = 2;
const int EE_ADDR_CHECKSUM = 3;     //Chosen by the controller to tell whether the saved layout is current
const int EE_ADDR_ASSIGNMENTS = 7;  //Same layout as the assignments array
const int EE_ADDR_LABELS = EE_ADDR_ASSIGNMENTS + sizeof(assignments);
const byte LABEL_SIZE = 24;         //Including the terminating 0
const byte N_LABELS = 10;           //Title, jog dial, keys 2-9 (907 bytes of the 1024 in total)

bool savedLayoutValid() {
  uint16_t magic;
  EEPROM.get(EE_ADDR_MAGIC, magic);
  return magic == EE_MAGIC && EEPROM.read(EE_ADDR_VERSION) == EE_VERSION;
}

uint32_t savedChecksum() {
  uint32_t checksum = 0;
  if (savedLayoutValid())
    EEPROM.get(EE_ADDR_CHECKSUM, checksum);
  return checksum;
}

//Replaces the assignments with the saved layout, returns false if there is none
bool loadSavedLayout() {
  if (!savedLayoutValid())
    return false;
  EEPROM.get(EE_ADDR_ASSIGNMENTS, assignments);
  return true;
}

//"E A <slot> <events>"  stores the events of a slot (see parseSlot())
//"E L <n> <text>"       stores label n (0 title, 1 jog dial, 2-9 keys), "|" starts a new line
//"E C <checksum>"       marks the saved layout as complete, answers "ok"
//"E X"                  deletes the saved layout
//The controller sends "E X" first, so a layout that was only partly written is never used.
void processStoreCommand() {
  if (serialBufferCount < 3 || serialBuffer[1] != ' ') {
    Serial.println("E: Bad format.");
    return;
  }
  switch (serialBuffer[2]) {
    case 'A': {
      byte key, pr;
      if (serialBufferCount < 6 || serialBuffer[3] != ' ' || !parseSlot(4, key, pr)) {
        Serial.println("E: Bad format.");
        return;
      }
      Event events[N_EVENTS];
      parseEvents(6, events);
      EEPROM.put(EE_ADDR_ASSIGNMENTS + (key * 2 + pr) * sizeof(events), events);
      break;
    }
    case 'L': {
      if (serialBufferCount < 5 || serialBuffer[3] != ' ' || serialBuffer[4] < '0' || serialBuffer[4] > '9') {
        Serial.println("E: Bad format.");
        return;
      }
      int addr = EE_ADDR_LABELS + (serialBuffer[4] - '0') * LABEL_SIZE;
      byte n = 0;
      for (byte i = 6; i < serialBufferCount && n < LABEL_SIZE - 1; i++, n++)
        EEPROM.update(addr + n, serialBuffer[i]);
      EEPROM.update(addr + n, 0);
      break;
    }
    case 'C': {
      uint32_t checksum = strtoul(serialBuffer + 4, NULL, 10);
      EEPROM.put(EE_ADDR_CHECKSUM, checksum);
      EEPROM.update(EE_ADDR_VERSION, EE_VERSION);
      EEPROM.put(EE_ADDR_MAGIC, EE_MAGIC);
      Serial.println("ok");
      break;
    }
    case 'X':
      EEPROM.put(EE_ADDR_MAGIC, (uint16_t)0);
      break;
    default:
      Serial.println("E: Bad format.");
  }
}

//The same areas the controller draws into, see Device.getAreaFor() in the Python code
void labelArea(byte n, int16_t &x, int16_t &y, int16_t &w, int16_t &h) {
  const int16_t banner = 12;
  if (n == 0) {         //Title
    x = 0; y = DISP_H - banner; w = DISP_W; h = banner;
  } else if (n == 1) {  //Jog dial
    x = 0; y = 0; w = DISP_W; h = banner;
  } else if (n <= 5) {
    x = DISP_W / 2; y = (5 - n) * DISP_H / 4 + banner; w = DISP_W / 2; h = DISP_H / 4 - 2 * banner;
  } else {
    x = 0; y = (9 - n) * DISP_H / 4 + banner; w = DISP_W / 2; h = DISP_H / 4 - 2 * banner;
  }
}

//Renders a saved label into the display buffer(s), using serialBuffer as scratch space
void writeLabel(byte n, bool again) {
  char text[LABEL_SIZE];
  for (byte i = 0; i < LABEL_SIZE; i++)
    text[i] = EEPROM.read(EE_ADDR_LABELS + n * LABEL_SIZE + i);
  text[LABEL_SIZE - 1] = 0;
  int16_t x, y, w, h;
  labelArea(n, x, y, w, h);
  int16_t bytesPerRow = w / 8;
  int16_t chunk = serialBufferSize / bytesPerRow;
  for (int16_t row = 0; row < h; row += chunk) {
    int16_t rows = min(chunk, h - row);
    labelRows((uint8_t*)serialBuffer, text, n == 0, w, h, row, rows);
    if (again)
      display.writeImageAgain((uint8_t*)serialBuffer, x, y + row, w, rows, false, false, false);
    else
      display.writeImage((uint8_t*)serialBuffer, x, y + row, w, rows, false, false, false);
  }
}

//Shows the labels of the saved layout (after initDisplay() cleared the screen)
void showSavedLabels() {
  for (byte n = 0; n < N_LABELS; n++)
    writeLabel(n, false);
  display.preparePartialRefresh(PARTIAL_REFRESH_REPEATS);
  display.refresh(true);
  for (byte n = 0; n < N_LABELS; n++)
    writeLabel(n, true);
  display.powerOff();
}
