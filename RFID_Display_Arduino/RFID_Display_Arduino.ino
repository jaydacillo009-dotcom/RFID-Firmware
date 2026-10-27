// Arduino Uno R3 / classic Nano is ONLY the 5V LCD adapter.
// LCD: VCC=5V, GND=GND, SDA=A4, SCL=A5.
// ESP32 GPIO17 -> D2; ESP32 GND -> GND. Leave D3 disconnected.
// All buttons, LEDs and buzzer are now wired to the ESP32.
// Library: LiquidCrystal I2C (init API).
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <SoftwareSerial.h>
#include <string.h>
LiquidCrystal_I2C lcd(0x27, 16, 2); // Try 0x3F if needed.
SoftwareSerial displayLink(2, 3); // RX, unused 5V TX: NEVER connect D3 to ESP32.
char line[40];
byte used = 0;
bool overflow = false;
unsigned long lastByteAt = 0;

void setup() {
  Wire.begin(); lcd.init(); lcd.backlight();
  lcd.print("Waiting ESP32");
  displayLink.begin(9600);
}
void loop() {
  if (used && millis() - lastByteAt > 250) { used = 0; overflow = false; }
  while (displayLink.available()) {
    char c = displayLink.read();
    lastByteAt = millis();
    if (c == '\r') continue;
    if (c == '\n') {
      line[used] = '\0';
      if (!overflow && used == 37 && strncmp(line, "@LCD:", 5) == 0) {
        // Always overwrite all 16 columns to erase previous text without flicker.
        lcd.setCursor(0, 0);
        for (byte i = 5; i < 21; ++i) lcd.write(line[i]);
        lcd.setCursor(0, 1);
        for (byte i = 21; i < 37; ++i) lcd.write(line[i]);
      }
      used = 0; overflow = false;
    } else if (used < sizeof(line) - 1) line[used++] = c;
    else overflow = true;
  }
}
