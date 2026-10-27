#pragma once
struct Preferences {
 std::map<std::string,std::string> entries;
 bool begin(const char*,bool){return true;}
 bool isKey(const char* key){return entries.count(key);}
 size_t putString(const char* key,const String& v){entries[key]=v.c_str();return v.length();}
 String getString(const char* key,const char* fallback){return isKey(key)?entries[key].c_str():fallback;}
 bool remove(const char* key){return entries.erase(key);}
};
