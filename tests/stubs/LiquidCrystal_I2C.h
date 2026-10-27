#pragma once
struct LiquidCrystal_I2C {
 char text[33];unsigned pos=0;
 LiquidCrystal_I2C(int,int,int){memset(text,' ',32);text[32]=0;}
 void init(){} void backlight(){}
 void setCursor(unsigned col,unsigned row){pos=row*16+col;}
 void write(char c){if(pos<32)text[pos++]=c;}
 void print(const char* s){while(*s)write(*s++);}
};
