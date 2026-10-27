// Actual ESP32 workflow with mocked pins/serial/NVS and real ArduinoJson.
#include <cassert>
#include <iostream>
#include <fstream>
#include "../RFID_Sender_ESP32/RFIDStation.h"
void reply(int status=200,const char* json="{\"ok\":true}"){
 JsonDocument body;assert(!deserializeJson(body,json));finishRequest(status,body);
}
void clearStateRequest(){if(pendingKind==RequestKind::state)reply();}
void sendQueued(){clearStateRequest();serviceRequests();}
void press(int pin){
 gpio[pin]=LOW;loop();clockMs+=35;loop();
 gpio[pin]=HIGH;loop();clockMs+=35;loop();
}
void start(){clearStateRequest();handleScan();assert(stage==Stage::student);}
void student(){
 handleUid("FFFFFFFF");assert(stage==Stage::item);
 assert(studentUid=="FFFFFFFF" && queuedKind==RequestKind::none);
}
void item(){
 handleUid("AABBCCDD");assert(stage==Stage::confirm);
 assert(queuedKind==RequestKind::none);
}
int main(int argc, char **argv){
 setup();assert(stage==Stage::idle && readerReady);
 press(PIN_MENU);assert(!receiveMode);
 press(PIN_MENU);assert(receiveMode);
 handleUid("01020304");assert(stage==Stage::idle);
 start();handleScan();assert(stage==Stage::student);
 handleUid("bad");assert(stage==Stage::student);
 // Accept an arbitrary student immediately, even without a laptop response.
 student();assert(studentUid=="FFFFFFFF");
 handleUid("FFFFFFFF");assert(stage==Stage::item); // Cannot reuse student as item.
 item();assert(gpio[PIN_GREEN]==LOW);
 press(PIN_MENU);assert(stage==Stage::idle && !journal.isKey("pending"));
 start();press(PIN_MENU);assert(stage==Stage::idle);
 start();student();press(PIN_MENU);assert(stage==Stage::idle && !studentUid.length());
 start();student();item();String id=requestId;
 // No validation previews and no transaction sent before final Scan.
 assert(Serial.output.find("/api/v1/preview")==std::string::npos);
 assert(Serial.output.find("/api/v1/commit")==std::string::npos);
 handleScan();assert(stage==Stage::saving && unresolvedCommit && journal.isKey("pending"));
 sendQueued();assert(pendingKind==RequestKind::commit);
 auto begin=Serial.output.rfind("@RFID:");JsonDocument wire;
 assert(!deserializeJson(wire,Serial.output.c_str()+begin+6));
 assert(wire["body"].size()==4 && strcmp(wire["body"]["student_uid"],"FFFFFFFF")==0);
 assert(strcmp(wire["body"]["mode"],"borrow")==0);
 handleMenu();assert(stage==Stage::saving);
 Serial.input="@RFID:{\"id\":\"wrong\",\"status\":200,\"body\":{\"ok\":true}}\n";
 readLaptop();assert(stage==Stage::saving && gpio[PIN_GREEN]==LOW);
 reply(503,"{\"ok\":false,\"message\":\"Offline\"}");
 assert(stage==Stage::confirm && unresolvedCommit && requestId==id);
 handleMenu();assert(stage==Stage::confirm && unresolvedCommit);
 requestId="";studentUid="";itemUid="";stage=Stage::idle;restoreJournal();
 assert(stage==Stage::confirm && requestId==id && unresolvedCommit);
 handleScan();sendQueued();assert(pendingKind==RequestKind::commit && requestId==id);
 reply();assert(stage==Stage::success && gpio[PIN_GREEN]==HIGH && gpio[PIN_RED]==LOW);
 assert(!journal.isKey("pending"));clockMs+=3001;loop();assert(stage==Stage::idle);
 // A save timeout must not become local success.
 start();student();item();handleScan();sendQueued();clockMs+=API_TIMEOUT_MS+1;serviceRequests();
 assert(stage==Stage::confirm && unresolvedCommit && gpio[PIN_GREEN]==LOW && gpio[PIN_RED]==HIGH);
 handleScan();sendQueued();reply();clockMs+=3001;loop();assert(stage==Stage::idle);
 // Return preserves mode and the same scanned student UID.
 handleMenu();start();student();item();handleScan();sendQueued();
 begin=Serial.output.rfind("@RFID:");assert(!deserializeJson(wire,Serial.output.c_str()+begin+6));
 assert(strcmp(wire["body"]["mode"],"return")==0);
 reply(409,"{\"ok\":false,\"message\":\"Wrong borrower\"}");
 assert(!unresolvedCommit);handleMenu();assert(stage==Stage::idle);
 // Oversized serial lines cannot hide the next correctly correlated response.
 start();student();item();handleScan();sendQueued();
 Serial.input=std::string(5000,'x')+"\n@RFID:{\"id\":\""+pendingId.c_str()+
 "\",\"status\":200,\"body\":{\"ok\":true}}\n";
 while(Serial.available())readLaptop();
 assert(stage==Stage::success);
 assert(Serial.output.find("/api/v1/preview")==std::string::npos);
 std::string frames=Serial2.output;
 for(size_t p=0;p<frames.size();){assert(frames.substr(p,5)=="@LCD:");assert(frames[p+37]=='\n');p+=38;}
 if(argc>1){std::ofstream out(argv[1]);out<<Serial.output;}
 std::cout<<"Station workflow checks passed\n";
}
