#include <cassert>
#include <iostream>
#include "../RFID_Display_Arduino/RFID_Display_Arduino.ino"
void feed(const std::string& text){displayLink.input=text;loop();}
int main(){
 setup();assert(std::string(lcd.text).substr(0,13)=="Waiting ESP32");
 std::string data="Successful!     Receive complete";
 assert(data.size()==32);feed("@LCD:"+data+"\n");assert(std::string(lcd.text)==data);
 feed("@LCD:bad\n");assert(std::string(lcd.text)==data);
 feed(std::string(100,'x')+"\n@LCD:"+std::string(32,' ')+"\n");
 assert(std::string(lcd.text)==std::string(32,' '));
 feed("@LCD:partial");clockMs+=251;loop();
 feed("@LCD:"+data+"\n");assert(std::string(lcd.text)==data);
 feed("UID:01020304\n");assert(std::string(lcd.text)==data);
 std::cout<<"LCD adapter framing checks passed\n";
}
