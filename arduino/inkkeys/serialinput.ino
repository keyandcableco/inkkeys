/*
 * E-Ink adaptive macro keyboard
 * See https://there.oughta.be/a/macro-keyboard
 * 
 * This part is related to receiving and parsing incoming commands from serial
 */

//Buffer to process serial input
const int serialBufferSize = 256;
char serialBuffer[serialBufferSize];
unsigned short serialBufferCount = 0; //Must be wider than a byte, or it wraps to 0 before the "too long" check can fire

//State while receiving an image
unsigned short expectingImageData = 0;
unsigned short imageDataTargetX, imageDataTargetY, imageDataTargetWidth, imageDataCurrentY;
unsigned short imageDataBytesPerRow, imageDataChunkSize; //Image rows are buffered and written in chunks of whole rows
bool imageDataAgain = false; //True for the second transfer after a refresh, which must also go to the panel's "previous" buffer

//Writes the rows buffered so far to the display controller.
//Writing many rows per call matters: GxEPD2 sleeps 1ms on every write call.
void flushImageRows() {
  unsigned short rows = serialBufferCount / imageDataBytesPerRow;
  if (rows == 0)
    return;
  if (imageDataAgain) //After a partial refresh, both panel buffers need the new content or the next refresh ghosts
    display.writeImageAgain((uint8_t*)serialBuffer, imageDataTargetX, imageDataCurrentY, imageDataTargetWidth, rows, false, false, false);
  else
    display.writeImage((uint8_t*)serialBuffer, imageDataTargetX, imageDataCurrentY, imageDataTargetWidth, rows, false, false, false);
  imageDataCurrentY += rows;
  serialBufferCount = 0;
}

//Output an error message with index
void printErrorWithIndex(const char * msg, byte i) {
  Serial.print("E: ");
  Serial.print(msg);
  Serial.print(" at index ");
  Serial.print(i);
  Serial.println(":");
  Serial.println(serialBuffer);
}

//Called to process a small part of the serialBuffer to parse a delay event, returns the number of characters handled
byte processDelay(Event &event, byte i) {
  byte handled = 1;
  if (i+handled >= serialBufferCount) {
    printErrorWithIndex("No duration", i+handled);
    return 0;
  }
  unsigned short t = atoi(serialBuffer+i+handled);
  event.deviceAndType = DEVICE_DELAY;
  event.keycodeOrDelay = t;
  while (i+handled < serialBufferCount && serialBuffer[i+handled] >= '0' && serialBuffer[i+handled] <= '9')
    handled++;
  return handled;
}

//Called to process a small part of the serialBuffer to parse a consumer event, returns the number of characters handled
byte processConsumer(Event &event, byte i) {
  byte handled = 1;
  if (i+handled >= serialBufferCount) {
    printErrorWithIndex("No keycode", i+handled);
    return 0;
  }
  unsigned short code = atoi(serialBuffer+i+handled);
  while (i+handled < serialBufferCount && serialBuffer[i+handled] >= '0' && serialBuffer[i+handled] <= '9')
    handled++;
    
  if (i+handled >= serialBufferCount || serialBuffer[i+handled] == ' ') {
    event.deviceAndType = DEVICE_CONSUMER | TYPE_STROKE;
    event.keycodeOrDelay = code;
  } else {
    switch (serialBuffer[i+handled]) {
      case 'p':
        event.deviceAndType = DEVICE_CONSUMER | TYPE_PRESS;
        event.keycodeOrDelay = code;
        break;
      case 'r':
        event.deviceAndType = DEVICE_CONSUMER | TYPE_RELEASE;
        event.keycodeOrDelay = code;
        break;
      default:
        printErrorWithIndex("Type not supported", i+handled);
        return 0;
    }
    handled++;
  }
  return handled;
}

//Called to process a small part of the serialBuffer to parse a keyboard event, returns the number of characters handled
byte processKeyboard(Event &event, byte i) {
  byte handled = 1;
  if (i+handled >= serialBufferCount) {
    printErrorWithIndex("No keycode", i+handled);
    return 0;
  }
  unsigned short code = atoi(serialBuffer+i+handled);
  while (i+handled < serialBufferCount && serialBuffer[i+handled] >= '0' && serialBuffer[i+handled] <= '9')
    handled++;
    
  if (i+handled >= serialBufferCount || serialBuffer[i+handled] == ' ') {
    event.deviceAndType = DEVICE_KEYBOARD | TYPE_STROKE;
    event.keycodeOrDelay = code;
  } else {
    switch (serialBuffer[i+handled]) {
      case 'p':
        event.deviceAndType = DEVICE_KEYBOARD | TYPE_PRESS;
        event.keycodeOrDelay = code;
        break;
      case 'r':
        event.deviceAndType = DEVICE_KEYBOARD | TYPE_RELEASE;
        event.keycodeOrDelay = code;
        break;
      default:
        printErrorWithIndex("Type not supported", i+handled);
        return 0;
    }
    handled++;
  }
  return handled;
}

//Called to process a small part of the serialBuffer to parse a mouse event, returns the number of characters handled
byte processMouse(Event &event, byte i) {
  byte handled = 1;
  if (i+handled >= serialBufferCount) {
    printErrorWithIndex("No keycode", i+handled);
    return 0;
  }
  unsigned short code;
  switch (serialBuffer[i+handled]) {
    case 'x':
      code = MOUSEAXIS_X << 8;
      handled++;
      break;
    case 'y':
      code = MOUSEAXIS_Y << 8;
      handled++;
      break;
    case 'w':
      code = MOUSEAXIS_WHEEL << 8;
      handled++;
      break;
    default:
      byte buttoncode = atoi(serialBuffer+i+handled);
      code = (MOUSEAXIS_BUTTON << 8) | buttoncode;
      while (i+handled < serialBufferCount && serialBuffer[i+handled] >= '0' && serialBuffer[i+handled] <= '9')
        handled++;
      break;
  }

  if (i+handled >= serialBufferCount || serialBuffer[i+handled] == ' ') {
    event.deviceAndType = DEVICE_MOUSE | TYPE_STROKE;
    event.keycodeOrDelay = code;
  } else {
    switch (serialBuffer[i+handled]) {
      case 'p':
        event.deviceAndType = DEVICE_MOUSE | TYPE_PRESS;
        event.keycodeOrDelay = code;
        handled++;
        break;
      case 'r':
        event.deviceAndType = DEVICE_MOUSE | TYPE_RELEASE;
        event.keycodeOrDelay = code;
        handled++;
        break;
      case 'i': {
        handled++;
        if (i+handled >= serialBufferCount) {
          printErrorWithIndex("Increment without value", i+handled);
          return 0;
        }
        int8_t inc = atoi(serialBuffer+i+handled);
        event.deviceAndType = DEVICE_MOUSE | TYPE_INCREMENT;
        event.keycodeOrDelay = code | (inc & 0xff);
        while (i+handled < serialBufferCount && ((serialBuffer[i+handled] >= '0' && serialBuffer[i+handled] <= '9') || serialBuffer[i+handled] == '-'))
          handled++;
        break;
      }
      default:
        printErrorWithIndex("Type not supported", i+handled);
        return 0;
    }
  }
  return handled;
}

//Parses an assignment slot like "2p", "R+" or "P-" at serialBuffer[i]: keys 1-9 pressed/released,
//R the jog dial turned, P the jog dial turned while it is pressed. Returns false if it is not one.
bool parseSlot(byte i, byte &key, byte &pr) {
  char k = serialBuffer[i];
  if (k >= '1' && k <= '9')
    key = k - '1';
  else if (k == 'R')
    key = 9;
  else if (k == 'P')
    key = 10;
  else
    return false;
  char t = serialBuffer[i+1];
  if (t == 'p' || t == '+')
    pr = 0;
  else if (t == 'r' || t == '-')
    pr = 1;
  else
    return false;
  return true;
}

//Parses the events starting at serialBuffer[i], each preceded by a space, into events[N_EVENTS].
//Unused entries are set to empty events, so the sequence ends there.
void parseEvents(byte i, Event events[]) {
  byte event = 0;
  while (i < serialBufferCount && event < N_EVENTS) {
    if (serialBuffer[i] != ' ') {
      printErrorWithIndex("Event not separated by white-space", i);
      break;
    }
    i++;
    if (i+1 >= serialBufferCount) {
      printErrorWithIndex("Sudden end", i);
      break;
    }

    byte processed = 0;
    switch (serialBuffer[i]) {
      case 'd':
        processed = processDelay(events[event], i);
        break;
      case 'c':
        processed = processConsumer(events[event], i);
        break;
      case 'k':
        processed = processKeyboard(events[event], i);
        break;
      case 'm':
        processed = processMouse(events[event], i);
        break;
      default:
        printErrorWithIndex("Unknown device", i);
    }

    if (processed == 0)
      break;
    event++;
    i += processed;
  }
  for (; event < N_EVENTS; event++) {
    events[event].deviceAndType = DEVICE_NONE;
  }
}

//"A <slot> <events>": assigns events to a key, see parseSlot()
void processAssignCommand() {
  byte key, pr;
  if (serialBufferCount < 4 || serialBuffer[1] != ' ' || !parseSlot(2, key, pr)) {
    printErrorWithIndex("Bad format", 2);
    return;
  }
  parseEvents(4, assignments[key][pr]);
}

//"X <events>": runs events right away. This lets the controller trigger actions itself,
//for long presses, double taps, key combinations and macros longer than N_EVENTS.
void processExecuteCommand() {
  Event events[N_EVENTS];
  parseEvents(1, events);
  executeEvents(events);
}

//"T <text>": types text through the keyboard layout. "\n" types Enter, "\\" a backslash.
void processTypeCommand() {
  for (byte i = 2; i < serialBufferCount; i++) {
    if (serialBuffer[i] == '\\' && i+1 < serialBufferCount) {
      i++;
      if (serialBuffer[i] == 'n')
        BootKeyboard.write(KEY_ENTER);
      else
        BootKeyboard.write((uint8_t)serialBuffer[i]);
    } else {
      BootKeyboard.write((uint8_t)serialBuffer[i]);
    }
  }
}

//"O <option> <value>": "O A 1" speeds up turning the jog dial quickly, "O A 0" turns that off
void processOptionCommand() {
  if (serialBufferCount < 5 || serialBuffer[1] != ' ' || serialBuffer[3] != ' ') {
    Serial.println("E: Bad format.");
    return;
  }
  switch (serialBuffer[2]) {
    case 'A':
      rotaryAcceleration = serialBuffer[4] == '1';
      break;
    default:
      Serial.println("E: Unknown option.");
  }
}

//Prints events in the format they are assigned with
void printEvents(Event events[]) {
  for (byte e = 0; e < N_EVENTS; e++) {
    byte device = events[e].deviceAndType & 0x0f;
    byte etype = events[e].deviceAndType & 0xf0;
    unsigned short value = events[e].keycodeOrDelay;
    if (device == DEVICE_NONE)
      break;
    Serial.print(' ');
    if (device == DEVICE_DELAY) {
      Serial.print('d');
      Serial.print(value);
      continue;
    }
    Serial.print(device == DEVICE_CONSUMER ? 'c' : device == DEVICE_KEYBOARD ? 'k' : 'm');
    if (device == DEVICE_MOUSE && (value >> 8) != MOUSEAXIS_BUTTON)
      Serial.print("?xyw"[(value >> 8) & 3]);
    else
      Serial.print(device == DEVICE_MOUSE ? (value & 0xff) : value);
    if (etype == TYPE_PRESS)
      Serial.print('p');
    else if (etype == TYPE_RELEASE)
      Serial.print('r');
    else if (etype == TYPE_INCREMENT) {
      Serial.print('i');
      Serial.print((int8_t)(value & 0xff));
    }
  }
  Serial.println();
}

//"G <slot>": prints the events assigned to a slot as "= <slot> <events>"
void processGetCommand() {
  byte key, pr;
  if (serialBufferCount < 4 || serialBuffer[1] != ' ' || !parseSlot(2, key, pr)) {
    printErrorWithIndex("Bad format", 2);
    return;
  }
  Serial.print("= ");
  Serial.print(serialBuffer[2]);
  Serial.print(serialBuffer[3]);
  printEvents(assignments[key][pr]);
}

void processDisplayCommand() {
  if (serialBufferCount < 3 || serialBuffer[1] != ' ') {
    Serial.println("E: Bad format.");
    return;
  }
  byte i = 2;
  imageDataTargetX = atoi(serialBuffer + i);
  while (i < serialBufferCount && serialBuffer[i] >= '0' && serialBuffer[i] <= '9')
    i++;
  if (i+1 >= serialBufferCount || serialBuffer[i] != ' ') {
    Serial.println("E: Bad format.");
    return;
  }
  i++;
  imageDataTargetY = atoi(serialBuffer + i);
  while (i < serialBufferCount && serialBuffer[i] >= '0' && serialBuffer[i] <= '9')
    i++;
  if (i+1 >= serialBufferCount || serialBuffer[i] != ' ') {
    Serial.println("E: Bad format.");
    return;
  }
  i++;
  imageDataTargetWidth = atoi(serialBuffer + i);
  while (i < serialBufferCount && serialBuffer[i] >= '0' && serialBuffer[i] <= '9')
    i++;
  if (i+1 >= serialBufferCount || serialBuffer[i] != ' ') {
    Serial.println("E: Bad format.");
    return;
  }
  i++;
  unsigned short imageDataTargetHeight = atoi(serialBuffer + i);
  while (i < serialBufferCount && serialBuffer[i] >= '0' && serialBuffer[i] <= '9')
    i++;
  //Optional trailing " a": this is the repeat of an image after a refresh
  imageDataAgain = (i+1 < serialBufferCount && serialBuffer[i] == ' ' && serialBuffer[i+1] == 'a');
  imageDataBytesPerRow = (imageDataTargetWidth+7)/8;
  if (imageDataBytesPerRow == 0 || imageDataBytesPerRow > serialBufferSize) {
    Serial.println("E: Bad format.");
    return;
  }
  imageDataChunkSize = (serialBufferSize / imageDataBytesPerRow) * imageDataBytesPerRow;
  expectingImageData = imageDataBytesPerRow*imageDataTargetHeight;
  imageDataCurrentY = imageDataTargetY;
}

void processInfoCommand() {
  if (serialBufferCount > 1) {
    Serial.println("E: Bad format.");
    return;
  }
  Serial.println("Inkkeys");
  Serial.println("TEST 0");
  Serial.println("VERSION 2"); //Supports the X, T, O, E and G commands and P slots
  Serial.print("N_LED ");
  Serial.println(N_LED);
  Serial.print("DISP_W ");
  Serial.println(DISP_W);
  Serial.print("DISP_H ");
  Serial.println(DISP_H);
  Serial.print("ROT_CIRCLE_STEPS ");
  Serial.println(ROT_CIRCLE_STEPS);
  Serial.print("SAVED ");
  Serial.println(savedChecksum()); //0 if no layout is saved on the keyboard
  Serial.println("Done");
}

void processLEDCommand() {
  if (serialBufferCount != 7*N_LED+1) {
    Serial.println("E: Bad format.");
    return;
  }
  for (byte i = 0; i < N_LED; i++) {
    leds.setPixelColor(i, strtol(&serialBuffer[7*i+1], NULL, 16));
  }
  leds.show();
}

//"R p", "R f" or "R o". A partial refresh takes an optional repeat count ("R p 4"), see PARTIAL_REFRESH_REPEATS.
void processRefreshCommand() {
  if (serialBufferCount < 3 || serialBuffer[1] != ' ' || (serialBuffer[2] != 'p' && serialBuffer[2] != 'f' && serialBuffer[2] != 'o')
      || (serialBufferCount > 3 && (serialBuffer[2] != 'p' || serialBufferCount < 5 || serialBuffer[3] != ' '))) {
    Serial.println("E: Bad format.");
    return;
  }
  switch (serialBuffer[2]) {
    case 'p':
      display.preparePartialRefresh(serialBufferCount > 3 ? atoi(serialBuffer + 4) : PARTIAL_REFRESH_REPEATS);
      display.refresh(true);
      break;
    case 'f':
      display.refresh(false);
      break;
    case 'o':
      display.powerOff();
      break;
  }
  Serial.println("ok");
}

//Read from Serial in and react to enter (carriage return)
void handleSerialInput() {
  //Handle up to one USB packet per call instead of one byte, so image
  //transfers are fast but keys and the jog dial are still polled often.
  for (byte n = 0; n < 64 && Serial.available() > 0; n++) {
    char c = Serial.read();

    if (expectingImageData == 0 && c == '\n') {
      //Carriage return. Command ends and needs to be processed
      if (serialBufferCount == serialBufferSize) {
        Serial.println("E: Command too long.");
      } else if (serialBufferCount > 0) {
        serialBuffer[serialBufferCount] = 0;
        switch (serialBuffer[0]) {
          case 'A': //Assign buttons
            processAssignCommand();
            break;
          case 'D':
            processDisplayCommand();
            break;
          case 'I': //Request device info
            processInfoCommand();
            break;
          case 'L': //Set LEDs
            processLEDCommand();
            break;
          case 'R': //Trigger refresh
            processRefreshCommand();
            break;
          case 'X': //Run events now
            processExecuteCommand();
            break;
          case 'T': //Type text
            processTypeCommand();
            break;
          case 'O': //Set an option
            processOptionCommand();
            break;
          case 'E': //Save a layout on the keyboard
            processStoreCommand();
            break;
          case 'G': //Print an assignment
            processGetCommand();
            break;
          default:  //Inknown command
            Serial.print("E: Unknown command: ");
            Serial.println(serialBuffer);
            break;
        }
        
      }
      
      //Command was handled. Reset buffer
      serialBufferCount = 0;
      
    } else {
      //Just a normal character or part of a transferred image. Store it in the buffer.
      if (serialBufferCount < serialBufferSize) {
        serialBuffer[serialBufferCount] = c;
        serialBufferCount++;

        if (expectingImageData > 0) {
          expectingImageData--;
          if (serialBufferCount >= imageDataChunkSize || expectingImageData == 0)
            flushImageRows();
        }
      }
    }
  }
}
