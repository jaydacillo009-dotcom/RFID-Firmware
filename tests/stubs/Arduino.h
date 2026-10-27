#pragma once
#include <cstdint>
#include <cstring>
#include <string>
#include <map>
using byte = uint8_t;
constexpr int HIGH=1, LOW=0, INPUT_PULLUP=2, OUTPUT=3, SERIAL_8N1=0;
unsigned long clockMs=0;
int gpio[40]={};
unsigned long millis(){return clockMs;}
void delay(unsigned long ms){clockMs+=ms;}
void pinMode(int p,int mode){if(mode==INPUT_PULLUP)gpio[p]=HIGH;}
int digitalRead(int p){return gpio[p];}
void digitalWrite(int p,int v){gpio[p]=v;}
void tone(int,int){}
void noTone(int){}
class String {
  std::string value;
public:
  String()=default;
  String(const char* s):value(s?s:""){}
  size_t length()const{return value.size();}
  const char* c_str()const{return value.c_str();}
  void reserve(size_t n){value.reserve(n);}
  char operator[](size_t n)const{return value[n];}
  String& operator+=(char c){value+=c;return *this;}
  bool operator==(const String& other)const{return value==other.value;}
  bool operator!=(const String& other)const{return !(*this==other);}
  size_t write(uint8_t c){value+=char(c);return 1;}
  size_t write(const uint8_t* s,size_t n){value.append((const char*)s,n);return n;}
};
struct Port {
  std::string input,output;
  void begin(int,int=0,int=-1,int=-1){}
  int available(){return input.size();}
  int read(){char c=input[0];input.erase(0,1);return c;}
  void print(const char* s){output+=s;}
  void print(const String& s){output+=s.c_str();}
  void print(char c){output+=c;}
  void println(){output+='\n';}
  void println(const char* s){print(s);println();}
  void println(const String& s){print(s);println();}
  size_t write(uint8_t c){output+=char(c);return 1;}
  size_t write(const uint8_t* s,size_t n){output.append((const char*)s,n);return n;}
} Serial,Serial2;
