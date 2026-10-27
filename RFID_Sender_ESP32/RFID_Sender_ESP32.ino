// ESP32 owns the RFID reader, Scan/Menu buttons, buzzer, LEDs and API workflow.
// The laptop forwards USB serial requests; Arduino drives only the 5V LCD.
// Install MFRC522 and ArduinoJson 7.x. See ../RFID_WIRING.md for all connections.
#include "RFIDStation.h"
