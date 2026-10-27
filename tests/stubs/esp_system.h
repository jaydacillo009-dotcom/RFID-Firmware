#pragma once
void esp_fill_random(void* out,size_t n){static uint8_t x=0;auto p=(uint8_t*)out;while(n--)*p++=++x;}
