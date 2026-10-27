#pragma once
#include <Arduino.h>
#include <ArduinoJson.h>
#include <MFRC522.h>
#include <SPI.h>
#include <Preferences.h>
#include <esp_system.h>

// Classic ESP32 DevKit. Buttons connect to GND and use internal pull-ups.
constexpr uint8_t PIN_SCAN = 25, PIN_MENU = 26, PIN_BUZZER = 14;
constexpr uint8_t PIN_GREEN = 32, PIN_RED = 33;
constexpr uint8_t PIN_RFID_SS = 5, PIN_RFID_RST = 27;
// false: small passive piezo. true: active-HIGH buzzer module SIGNAL input.
constexpr bool ACTIVE_BUZZER = false;
constexpr unsigned long API_TIMEOUT_MS = 12000;

MFRC522 rfid(PIN_RFID_SS, PIN_RFID_RST);
Preferences journal;
bool journalReady = false, readerReady = false, journalFault = false;
enum class Stage { idle, student, item, confirm, saving, success };
enum class RequestKind { none, state, commit };
Stage stage = Stage::idle;
RequestKind pendingKind = RequestKind::none, queuedKind = RequestKind::none;
String studentUid, itemUid, requestId;
String pendingId, queuedBody;
bool receiveMode = true, unresolvedCommit = false;
unsigned long generation = 0, pendingGeneration = 0, pendingAt = 0;
unsigned long lastStateAttempt = 0, successAt = 0, beepUntil = 0, lastDisplayAt = 0;
bool stateDirty = true, stateAttempted = false, buzzerOn = false;
const char *publicStage = "idle";
char usbLine[4096];
size_t usbUsed = 0;
bool usbOverflow = false;
char displayText[33] = "";

struct Button {
  uint8_t pin;
  bool raw = HIGH, stable = HIGH;
  unsigned long changedAt = 0;
  explicit Button(uint8_t p) : pin(p) {}
  bool pressed() {
    bool value = digitalRead(pin);
    if (value != raw) { raw = value; changedAt = millis(); }
    if (value != stable && millis() - changedAt >= 30) {
      stable = value;
      return stable == LOW;
    }
    return false;
  }
};
Button scanButton(PIN_SCAN), menuButton(PIN_MENU);

void lights(bool green, bool red) {
  digitalWrite(PIN_GREEN, green ? HIGH : LOW);
  digitalWrite(PIN_RED, red ? HIGH : LOW);
}
void beep(bool good) {
  if (ACTIVE_BUZZER) digitalWrite(PIN_BUZZER, HIGH);
  else tone(PIN_BUZZER, good ? 2200 : 400);
  buzzerOn = true;
  beepUntil = millis() + (good ? 100 : 250);
}
void serviceBuzzer() {
  if (buzzerOn && static_cast<long>(millis() - beepUntil) >= 0) {
    if (ACTIVE_BUZZER) digitalWrite(PIN_BUZZER, LOW);
    else noTone(PIN_BUZZER);
    buzzerOn = false;
  }
}
void sendDisplay() {
  Serial2.print("@LCD:");
  Serial2.print(displayText);
  Serial2.print('\n');
  lastDisplayAt = millis();
}
void screen(const String &top, const String &bottom) {
  memset(displayText, ' ', 32);
  displayText[32] = '\0';
  const String rows[] = { top, bottom };
  for (size_t row = 0; row < 2; ++row) {
    for (size_t col = 0; col < 16 && col < rows[row].length(); ++col) {
      char c = rows[row][col];
      displayText[row * 16 + col] = (c >= 32 && c <= 126) ? c : '?';
    }
  }
  sendDisplay();
  Serial.print("Display: "); Serial.print(top); Serial.print(" | "); Serial.println(bottom);
}
void reportState(const char *value) {
  publicStage = value;
  stateDirty = true;
}
void idleScreen() {
  screen(receiveMode ? "Mode: RECEIVE" : "Mode: RETURN", "SCAN=start MENU");
}
String randomHex(size_t bytes) {
  static const char digits[] = "0123456789abcdef";
  String result;
  result.reserve(bytes * 2);
  for (size_t i = 0; i < bytes; ++i) {
    uint8_t value;
    esp_fill_random(&value, 1);
    result += digits[value >> 4]; result += digits[value & 15];
  }
  return result;
}
bool validUid(const String &uid) {
  size_t n = uid.length();
  if (n != 8 && n != 14 && n != 20) return false;
  for (size_t i = 0; i < n; ++i) {
    if (!((uid[i] >= '0' && uid[i] <= '9') || (uid[i] >= 'A' && uid[i] <= 'F'))) return false;
  }
  return true;
}
String transactionBody(bool committing) {
  JsonDocument body;
  // Receive means the student receives/borrows equipment, per the existing API.
  body["mode"] = receiveMode ? "borrow" : "return";
  body["student_uid"] = studentUid.c_str();
  if (itemUid.length()) body["item_uid"] = itemUid.c_str();
  else body["item_uid"] = nullptr;
  if (committing) body["request_id"] = requestId.c_str();
  String result;
  serializeJson(body, result);
  return result;
}
void resetSession() {
  ++generation; // Late replies must not change a newer session.
  queuedKind = RequestKind::none; queuedBody = "";
  studentUid = ""; itemUid = ""; requestId = "";
  unresolvedCommit = false;
  stage = Stage::idle;
  reportState("idle");
}
void failure(const String &message, const char *prompt) {
  lights(false, true); beep(false);
  screen(message, prompt);
  Serial.print("Error: "); Serial.println(message);
  reportState("error");
}
void queueRequest(RequestKind kind) {
  queuedKind = kind;
  queuedBody = transactionBody(kind == RequestKind::commit);
}
// One atomic NVS string preserves the exact idempotent request across USB reset.
// Opening a serial port often resets an ESP32; an uncertain save must survive it.
bool saveJournal(const String &body) {
  return journalReady && journal.putString("pending", body) == body.length();
}
bool clearJournal() {
  if (!journalReady) return false;
  if (!journal.isKey("pending")) return true;
  return journal.remove("pending");
}
void handleScan() {
  if (journalFault || (!readerReady && !unresolvedCommit)) { beep(false); return; }
  if (stage == Stage::idle) {
    lights(false, false); resetSession();
    stage = Stage::student;
    screen(receiveMode ? "RECEIVE" : "RETURN", "Tap student ID");
    reportState("scan_student"); beep(true);
  } else if (stage == Stage::confirm) {
    // Journal before sending, so a reset cannot create a fresh request ID.
    String body = transactionBody(true);
    if (!saveJournal(body)) {
      failure("Storage error", "Save not sent");
      return;
    }
    lights(false, false);
    unresolvedCommit = true;
    stage = Stage::saving;
    screen("Saving record", "Wait for server");
    queueRequest(RequestKind::commit);
  }
}
void handleMenu() {
  if (journalFault) { beep(false); return; }
  if (stage == Stage::saving || unresolvedCommit) {
    // A transmitted save may already exist. Retry its same ID; never claim cancel.
    screen(stage == Stage::saving ? "Saving record" : "Save uncertain", "SCAN to retry");
    beep(false);
    return;
  }
  lights(false, false);
  if (stage == Stage::idle || stage == Stage::success) {
    resetSession(); receiveMode = !receiveMode; idleScreen(); beep(true);
  } else {
    resetSession();
    screen("Scan cancelled", "SCAN=start MENU"); beep(false);
  }
}
void handleUid(const String &uid) {
  if (!validUid(uid)) return;
  if (stage == Stage::student) {
    lights(false, false); studentUid = uid;
    // Accept the first card locally. No student lookup or preview request.
    stage = Stage::item;
    screen("Student ID read", "Tap item RFID");
    beep(true); reportState("scan_item");
  } else if (stage == Stage::item) {
    if (uid == studentUid) {
      failure("Different tag!", "Tap item RFID");
      return;
    }
    lights(false, false); itemUid = uid;
    // Collect both UIDs before posting. The API checks item rules at commit.
    requestId = randomHex(16);
    stage = Stage::confirm;
    screen("Both IDs read", "SCAN=confirm");
    beep(true); reportState("confirm");
  }
}
void finishRequest(int status, const JsonDocument &body) {
  RequestKind kind = pendingKind;
  unsigned long completedGeneration = pendingGeneration;
  pendingKind = RequestKind::none;
  bool ok = status == 200 && body["ok"].is<bool>() && body["ok"].as<bool>();
  if (kind == RequestKind::state) {
    if (!ok) stateDirty = true; // Retry later, without blocking buttons or scans.
    return;
  }
  if (completedGeneration != generation) return;
  String message = body["message"] | "API request failed";
  if (kind == RequestKind::commit) {
    if (ok) {
      // Keep the record if deletion fails, so recovery still uses its same ID.
      if (!clearJournal()) {
        stage = Stage::confirm;
        failure("Saved; NVS error", "SCAN to retry");
        return;
      }
      unresolvedCommit = false;
      stage = Stage::success; successAt = millis();
      lights(true, false); beep(true);
      screen("Successful!", receiveMode ? "Receive complete" : "Return complete");
      reportState("success");
    } else {
      stage = Stage::confirm;
      // Network/server failures can occur AFTER the database committed.
      // A definite 4xx rejection permits cancellation; ambiguous outcomes do not.
      if (status >= 400 && status < 500 && status != 408 && status != 429) {
        if (clearJournal()) unresolvedCommit = false;
      }
      failure(message, "SCAN to retry");
    }
  }
}
void consumeReply() {
  if (strncmp(usbLine, "@RFID:", 6) != 0) return;
  JsonDocument reply;
  if (deserializeJson(reply, usbLine + 6)) return;
  if (pendingKind == RequestKind::none || !reply["id"].is<const char *>() ||
      pendingId != reply["id"].as<const char *>()) return;
  if (!reply["body"].is<JsonObject>() || !reply["status"].is<int>()) return;
  JsonDocument body;
  body.set(reply["body"]);
  finishRequest(reply["status"].as<int>(), body);
}
void readLaptop() {
  // Bounded work keeps Menu responsive even with noisy serial input.
  size_t budget = 512;
  while (budget-- && Serial.available()) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      usbLine[usbUsed] = '\0';
      if (!usbOverflow) consumeReply();
      usbUsed = 0; usbOverflow = false;
    } else if (usbUsed < sizeof(usbLine) - 1) usbLine[usbUsed++] = c;
    else usbOverflow = true;
  }
}
void serviceRequests() {
  if (pendingKind != RequestKind::none && millis() - pendingAt >= API_TIMEOUT_MS) {
    JsonDocument error;
    error["ok"] = false; error["message"] = "Laptop/API offline";
    finishRequest(503, error);
  }
  if (pendingKind != RequestKind::none) return;
  JsonDocument body;
  const char *path;
  if (queuedKind != RequestKind::none) {
    pendingKind = queuedKind; queuedKind = RequestKind::none;
    if (deserializeJson(body, queuedBody.c_str())) {
      pendingGeneration = generation;
      JsonDocument error; error["message"] = "Bad request JSON";
      finishRequest(400, error);
      return;
    }
    queuedBody = "";
    path = "/api/v1/commit";
  } else if (stateDirty && (!stateAttempted || millis() - lastStateAttempt >= 1000)) {
    pendingKind = RequestKind::state;
    body["mode"] = receiveMode ? "borrow" : "return";
    body["stage"] = publicStage;
    stateDirty = false; stateAttempted = true; lastStateAttempt = millis();
    path = "/api/v1/state";
  } else return;
  pendingGeneration = generation; pendingAt = millis(); pendingId = randomHex(8);
  JsonDocument request;
  request["id"] = pendingId.c_str(); request["path"] = path;
  request["body"] = body.as<JsonVariant>();
  Serial.print("@RFID:"); serializeJson(request, Serial); Serial.println();
}
String readUid() {
  if (!rfid.PICC_IsNewCardPresent() || !rfid.PICC_ReadCardSerial()) return "";
  static const char digits[] = "0123456789ABCDEF";
  String uid;
  for (uint8_t i = 0; i < rfid.uid.size; ++i) {
    uid += digits[rfid.uid.uidByte[i] >> 4]; uid += digits[rfid.uid.uidByte[i] & 15];
  }
  rfid.PICC_HaltA(); rfid.PCD_StopCrypto1();
  return uid;
}
void restoreJournal() {
  String saved = journal.getString("pending", "");
  if (!saved.length()) return;
  JsonDocument body;
  bool bad = static_cast<bool>(deserializeJson(body, saved.c_str()));
  String mode = body["mode"] | "";
  String student = body["student_uid"] | "";
  String item = body["item_uid"] | "";
  String id = body["request_id"] | "";
  bad = bad || (mode != "borrow" && mode != "return") || !validUid(student) ||
        !validUid(item) || id.length() != 32;
  for (size_t i = 0; i < id.length(); ++i) {
    if (!((id[i] >= '0' && id[i] <= '9') || (id[i] >= 'a' && id[i] <= 'f'))) bad = true;
  }
  if (bad) {
    journalFault = true; failure("Recovery error", "Check USB log");
    return;
  }
  receiveMode = mode == "borrow"; studentUid = student; itemUid = item; requestId = id;
  unresolvedCommit = true; stage = Stage::confirm;
  lights(false, true); screen("Recover last save", "SCAN to retry"); reportState("confirm");
}
void setup() {
  Serial.begin(115200);
  Serial2.begin(9600, SERIAL_8N1, 16, 17); // GPIO16 RX stays disconnected.
  pinMode(PIN_SCAN, INPUT_PULLUP); pinMode(PIN_MENU, INPUT_PULLUP);
  pinMode(PIN_BUZZER, OUTPUT); pinMode(PIN_GREEN, OUTPUT); pinMode(PIN_RED, OUTPUT);
  digitalWrite(PIN_BUZZER, LOW); lights(false, false);
  SPI.begin(18, 19, 23, PIN_RFID_SS); rfid.PCD_Init();
  delay(50);
  byte version = rfid.PCD_ReadRegister(MFRC522::VersionReg);
  readerReady = version != 0x00 && version != 0xFF;
  journalReady = journal.begin("rfid-station", false);
  if (!journalReady) {
    journalFault = true; failure("Storage offline", "Restart ESP32");
  } else {
    idleScreen(); restoreJournal();
    if (!readerReady && !unresolvedCommit && !journalFault) failure("RFID not found", "Check wiring");
  }
}
void loop() {
  serviceBuzzer();
  // Process Menu before any reply/card to prevent a cancelled scan progressing.
  bool menuPressed = menuButton.pressed(), scanPressed = scanButton.pressed();
  if (menuPressed) handleMenu();
  else if (scanPressed) handleScan();
  readLaptop();
  // Drain ignored cards too: a card presented before Scan must not be accepted later.
  if (readerReady && !journalFault) {
    String uid = readUid();
    if (uid.length()) handleUid(uid);
  }
  if (stage == Stage::success && millis() - successAt >= 3000) {
    resetSession(); idleScreen(); // Keep green lit until the next action.
  }
  serviceRequests();
  if (millis() - lastDisplayAt >= 1000) sendDisplay(); // Recover Arduino-only resets.
  delay(2);
}
