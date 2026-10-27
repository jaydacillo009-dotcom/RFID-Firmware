#pragma once
struct MFRC522 {
 enum Register {VersionReg};
 struct {uint8_t size=4;uint8_t uidByte[10]={};} uid;
 MFRC522(int,int){}
 void PCD_Init(){}
 byte PCD_ReadRegister(Register){return 0x92;}
 bool PICC_IsNewCardPresent(){return false;}
 bool PICC_ReadCardSerial(){return false;}
 void PICC_HaltA(){}
 void PCD_StopCrypto1(){}
};
