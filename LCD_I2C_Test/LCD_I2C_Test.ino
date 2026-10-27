// 16x2 LCD with a PCF8574 I2C backpack.
// Library: LiquidCrystal I2C (LiquidCrystal_I2C.h, init() API).
// Classic ESP32 DevKit: SDA -> GPIO21, SCL -> GPIO22.
// For a 5V LCD backpack, use a bidirectional I2C level shifter:
// ESP32 side LV=3.3V, LCD side HV=5V, with a common GND.
// LCD VCC -> 5V. Do not connect 5V I2C pull-ups directly to ESP32.
#include <Wire.h>
#include <LiquidCrystal_I2C.h>

// Change this to the address printed in Serial Monitor if needed.
const uint8_t LCD_ADDRESS = 0x27;
const int SDA_PIN = 21;
const int SCL_PIN = 22;
LiquidCrystal_I2C lcd(LCD_ADDRESS, 16, 2);

void setup() {
  Serial.begin(115200);
  Wire.begin(SDA_PIN, SCL_PIN, 100000);
  delay(100);

  Serial.println("Scanning I2C bus...");
  bool lcdFound = false;
  for (uint8_t address = 1; address < 127; address++) {
    Wire.beginTransmission(address);
    if (Wire.endTransmission() == 0) {
      Serial.print("Device at 0x");
      if (address < 16) Serial.print('0');
      Serial.println(address, HEX);
      if (address == LCD_ADDRESS) lcdFound = true;
    }
  }

  if (!lcdFound) {
    Serial.println("LCD address not found. Check wiring and LCD_ADDRESS.");
    while (true) delay(1000);
  }

  lcd.init();
  lcd.backlight();
  lcd.setCursor(0, 0);
  lcd.print("LCD 16x2 TEST OK");
  lcd.setCursor(0, 1);
  lcd.print("Hello, world!");
  delay(2000);

  // Check all 16 character positions on both rows.
  lcd.clear();
  lcd.print("0123456789ABCDEF");
  lcd.setCursor(0, 1);
  lcd.print("abcdefghijklmnop");
  delay(2000);

  // Briefly blink the backlight to test its control.
  lcd.noBacklight();
  delay(500);
  lcd.backlight();
  lcd.clear();
  lcd.print("LCD 16x2 TEST OK");
  Serial.println("LCD initialized. Check text and contrast on display.");
}

void loop() {
  lcd.setCursor(0, 1);
  lcd.print("Seconds:        ");
  lcd.setCursor(9, 1);
  lcd.print(millis() / 1000UL);
  delay(1000);
}
