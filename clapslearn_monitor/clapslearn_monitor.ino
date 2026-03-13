/*
 * Universal Trading Monitor - ESP32 & ESP8266 Compatible
 * =======================================================
 * Auto-detects board and adapts code automatically
 * 
 * Compatible Boards:
 * - ESP32 DevKit V1, ESP32-WROOM, ESP32-WROVER
 * - NodeMCU (ESP8266), WEMOS D1 Mini, ESP-12F
 * 
 * Hardware Requirements:
 * - 1.3" OLED Display (SSD1306, 128x64, I2C)
 * - Push Button (optional)
 * - Buzzer (optional)
 * 
 * Pin Connections:
 * ESP32:  SDA=GPIO21, SCL=GPIO22, BTN=GPIO4,  BUZZER=GPIO18, LED=GPIO2
 * ESP8266: SDA=GPIO4 (D2), SCL=GPIO5 (D1), BTN=GPIO12 (D6), BUZZER=GPIO14 (D5), LED=GPIO2 (D4)
 */

// ============ BOARD DETECTION & LIBRARIES ============
#ifdef ESP32
  #include <WiFi.h>
  #include <HTTPClient.h>
  #include <WiFiClient.h>
  #define BOARD_NAME "ESP32"
  #define LED_ON LOW
  #define LED_OFF HIGH
  
  // ESP32 Default Pins
  #define PIN_SDA         21
  #define PIN_SCL         22
  #define PIN_BUTTON      4
  #define PIN_BUZZER      18
  #define PIN_LED         2
  
  // ESP32 Timing (faster)
  #define DATA_INTERVAL   5000
  #define DISPLAY_FPS     20
  
#elif defined(ESP8266)
  #include <ESP8266WiFi.h>
  #include <ESP8266HTTPClient.h>
  #include <WiFiClient.h>
  #define BOARD_NAME "ESP8266"
  #define LED_ON LOW      // ESP8266 LED is active LOW
  #define LED_OFF HIGH
  
  // ESP8266 NodeMCU/D1 Mini Pins
  #define PIN_SDA         4   // D2
  #define PIN_SCL         5   // D1
  #define PIN_BUTTON      12  // D6
  #define PIN_BUZZER      14  // D5
  #define PIN_LED         2   // D4 (Built-in)
  
  // ESP8266 Timing (more conservative)
  #define DATA_INTERVAL   10000
  #define DISPLAY_FPS     10
  
#else
  #error "Unsupported board! Please use ESP32 or ESP8266"
#endif

#include <ArduinoJson.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

// ============ MELODY DEFINITIONS ============
enum Melody {
  MELODY_BOOT,
  MELODY_BUTTON,
  MELODY_ALERT,
  MELODY_SUCCESS,
  MELODY_ERROR
};

void playMelody(Melody melody);

// ============ CONFIGURATION ============
const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASS = "YOUR_WIFI_PASSWORD";
const char* SERVER_URL = "https://coolify.themelon.in";
const char* DEVICE_ID = "universal_trading_display";

// Display
#define SCREEN_WIDTH    128
#define SCREEN_HEIGHT   64
#define OLED_ADDR       0x3C
#define OLED_RESET      -1

// Timing
#define ALERT_INTERVAL      2000
#define AUTO_CYCLE_TIME     8000
#define WIFI_TIMEOUT        10000
#define HTTP_TIMEOUT        5000
#define BUTTON_DEBOUNCE     300
#define ALERT_DURATION      5000
#define WIFI_RECONNECT_INT  30000

// LED blink patterns
#define BLINK_SLOW    1000
#define BLINK_FAST    200
#define BLINK_ALERT   100

Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);
WiFiClient wifiClient;

// ============ DATA STRUCTURES ============
struct Position {
  char symbol[12];
  float entryPrice;
  float ltp;
  float sl;
  float tp;
  int quantity;
  float pnl;
  float pnlPercent;
  bool isPaper;
};

struct DailyStats {
  int totalTrades;
  float paperPnl;
  float livePnl;
  int paperTrades;
  int liveTrades;
};

struct StrategyConfig {
  float riskPercent;
  float minRR;
  float atrSl;
  float atrTp;
  bool paperTrading;
};

struct TradingData {
  bool systemEnabled;
  bool marketOpen;
  int openPositions;
  DailyStats daily;
  StrategyConfig strategy;
};

// Global state
TradingData data = {false, false, 0, {0, 0, 0, 0, 0}, {1.0, 2.0, 1.5, 3.0, true}};
Position positions[10];
int positionCount = 0;

// Screens
enum Screen {
  SCR_OVERVIEW,
  SCR_POSITIONS,
  SCR_STRATEGY,
  SCR_NETWORK,
  SCR_COUNT
};
Screen currentScreen = SCR_OVERVIEW;

// Timing
unsigned long lastDataFetch = 0;
unsigned long lastAlertCheck = 0;
unsigned long lastDisplayUpdate = 0;
unsigned long lastScreenCycle = 0;
unsigned long lastButtonPress = 0;
unsigned long lastWiFiCheck = 0;
unsigned long lastLedBlink = 0;
bool ledState = false;

// Button
bool btnPressed = false;

// Alert
bool alertActive = false;
char alertSymbol[12] = "";
float alertPrice = 0;
unsigned long alertStartTime = 0;

// ============ SETUP ============
void setup() {
  Serial.begin(115200);
  delay(100);
  
  #ifdef ESP8266
  yield(); // Let ESP8266 WiFi stack initialize
  #endif
  
  Serial.println(F("\n================================"));
  Serial.print(F("Trading Display - "));
  Serial.println(BOARD_NAME);
  Serial.println(F("================================\n"));
  
  // Pins
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  pinMode(PIN_LED, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);
  digitalWrite(PIN_LED, LED_OFF);
  
  // Init OLED
  Wire.begin(PIN_SDA, PIN_SCL);
  #ifdef ESP32
  Wire.setClock(400000); // 400kHz for ESP32
  #endif
  
  if(!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
    Serial.println(F("SSD1306 allocation failed"));
    while(1) {
      digitalWrite(PIN_LED, !digitalRead(PIN_LED));
      delay(100);
      #ifdef ESP8266
      yield();
      #endif
    }
  }
  
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  
  showBootScreen();
  connectWiFi();
  
  if (WiFi.status() == WL_CONNECTED) {
    fetchAllData();
  }
  
  playMelody(MELODY_BOOT);
  
  Serial.println(F("Setup complete!"));
  #ifdef ESP8266
  Serial.print(F("Free heap: "));
  Serial.println(ESP.getFreeHeap());
  #endif
}

// ============ MAIN LOOP ============
void loop() {
  unsigned long now = millis();
  
  handleLedStatus(now);
  handleButton();
  
  if (now - lastWiFiCheck >= WIFI_RECONNECT_INT) {
    checkWiFiConnection();
    lastWiFiCheck = now;
  }
  
  if (WiFi.status() == WL_CONNECTED && now - lastDataFetch >= DATA_INTERVAL) {
    fetchAllData();
    lastDataFetch = now;
  }
  
  if (WiFi.status() == WL_CONNECTED && now - lastAlertCheck >= ALERT_INTERVAL) {
    checkAlerts();
    lastAlertCheck = now;
  }
  
  if (now - lastScreenCycle >= AUTO_CYCLE_TIME) {
    nextScreen();
    lastScreenCycle = now;
  }
  
  if (now - lastDisplayUpdate >= (1000 / DISPLAY_FPS)) {
    updateDisplay();
    lastDisplayUpdate = now;
  }
  
  // Feed watchdog on ESP8266
  #ifdef ESP8266
  delay(1);
  yield();
  #endif
}

// ============ LED STATUS ============
void handleLedStatus(unsigned long now) {
  int blinkInterval;
  
  if (alertActive) {
    blinkInterval = BLINK_ALERT;
  } else if (WiFi.status() != WL_CONNECTED) {
    blinkInterval = BLINK_FAST;
  } else if (!data.systemEnabled) {
    blinkInterval = BLINK_FAST;
  } else {
    blinkInterval = BLINK_SLOW;
  }
  
  if (now - lastLedBlink >= blinkInterval) {
    ledState = !ledState;
    digitalWrite(PIN_LED, ledState ? LED_ON : LED_OFF);
    lastLedBlink = now;
  }
}

// ============ WIFI ============
void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  
  display.clearDisplay();
  display.setCursor(0, 0);
  display.println(F("Connecting WiFi..."));
  display.display();
  
  #ifdef ESP8266
  WiFi.mode(WIFI_STA);
  #endif
  
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  
  int attempts = 0;
  unsigned long startTime = millis();
  
  while (WiFi.status() != WL_CONNECTED && attempts < 40) {
    delay(250);
    #ifdef ESP8266
    yield();
    #endif
    Serial.print(".");
    
    if (attempts % 4 == 0) {
      display.print(".");
      display.display();
    }
    
    attempts++;
    
    if (millis() - startTime > WIFI_TIMEOUT) break;
  }
  
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print(F("\nWiFi Connected! IP: "));
    Serial.println(WiFi.localIP());
  } else {
    Serial.println(F("\nWiFi Connect Failed!"));
  }
}

void checkWiFiConnection() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println(F("WiFi disconnected, reconnecting..."));
    WiFi.disconnect();
    #ifdef ESP8266
    yield();
    #endif
    delay(100);
    #ifdef ESP8266
    yield();
    #endif
    connectWiFi();
  }
}

// ============ DATA FETCHING ============
void fetchAllData() {
  if (WiFi.status() != WL_CONNECTED) return;
  
  fetchESPStats();
  #ifdef ESP8266
  yield();
  #endif
  fetchPositions();
  #ifdef ESP8266
  yield();
  #endif
  fetchInsights();
}

void fetchESPStats() {
  HTTPClient http;
  String url = String(SERVER_URL) + "/api/esp/stats";
  
  #ifdef ESP32
  http.begin(wifiClient, url);
  #else
  http.begin(wifiClient, url);
  #endif
  
  http.setTimeout(HTTP_TIMEOUT);
  int httpCode = http.GET();
  
  if (httpCode == 200) {
    String payload = http.getString();
    
    #ifdef ESP32
    StaticJsonDocument<512> doc;
    #else
    StaticJsonDocument<384> doc;
    #endif
    
    DeserializationError error = deserializeJson(doc, payload);
    
    if (!error) {
      data.systemEnabled = doc["system_enabled"] | false;
      data.marketOpen = doc["market_open"] | false;
      data.openPositions = doc["open_positions"] | 0;
      data.strategy.paperTrading = doc["paper_trading"] | true;
      data.daily.paperPnl = doc["today_pnl"] | 0;
      data.daily.totalTrades = doc["today_trades"] | 0;
    }
  }
  
  http.end();
}

void fetchPositions() {
  HTTPClient http;
  String url = String(SERVER_URL) + "/api/esp/positions";
  
  http.begin(wifiClient, url);
  http.setTimeout(HTTP_TIMEOUT);
  int httpCode = http.GET();
  
  if (httpCode == 200) {
    String payload = http.getString();
    
    #ifdef ESP32
    StaticJsonDocument<2048> doc;
    #else
    StaticJsonDocument<768> doc;
    #endif
    
    DeserializationError error = deserializeJson(doc, payload);
    
    if (!error) {
      JsonArray posArray = doc["positions"];
      positionCount = 0;
      
      for (JsonObject pos : posArray) {
        #ifdef ESP32
        if (positionCount >= 10) break;
        #else
        if (positionCount >= 5) break;
        #endif
        
        strlcpy(positions[positionCount].symbol, pos["symbol"] | "", 12);
        positions[positionCount].entryPrice = pos["entry_price"] | 0;
        positions[positionCount].ltp = pos["ltp"] | 0;
        positions[positionCount].sl = pos["sl_price"] | 0;
        positions[positionCount].tp = pos["tp_price"] | 0;
        positions[positionCount].quantity = pos["quantity"] | 0;
        positions[positionCount].pnl = pos["pnl"] | 0;
        positions[positionCount].pnlPercent = pos["pnl_percent"] | 0;
        positions[positionCount].isPaper = pos["paper_trading"] | true;
        
        positionCount++;
      }
    }
  }
  
  http.end();
}

void fetchInsights() {
  HTTPClient http;
  String url = String(SERVER_URL) + "/api/insights";
  
  http.begin(wifiClient, url);
  http.setTimeout(HTTP_TIMEOUT);
  int httpCode = http.GET();
  
  if (httpCode == 200) {
    String payload = http.getString();
    
    #ifdef ESP32
    StaticJsonDocument<1024> doc;
    #else
    StaticJsonDocument<768> doc;
    #endif
    
    DeserializationError error = deserializeJson(doc, payload);
    
    if (!error) {
      JsonObject dailyStats = doc["daily_stats"];
      if (!dailyStats.isNull()) {
        for (JsonPair day : dailyStats) {
          JsonObject stats = day.value();
          data.daily.paperPnl = stats["paper_pnl"] | 0;
          data.daily.livePnl = stats["live_pnl"] | 0;
          data.daily.totalTrades = stats["trades"] | 0;
        }
      }
    }
  }
  
  http.end();
}

void checkAlerts() {
  HTTPClient http;
  String url = String(SERVER_URL) + "/api/esp/alert";
  
  http.begin(wifiClient, url);
  http.setTimeout(HTTP_TIMEOUT);
  int httpCode = http.GET();
  
  if (httpCode == 200) {
    String payload = http.getString();
    
    #ifdef ESP32
    StaticJsonDocument<256> doc;
    #else
    StaticJsonDocument<256> doc;
    #endif
    
    DeserializationError error = deserializeJson(doc, payload);
    
    if (!error) {
      const char* symbol = doc["symbol"];
      if (symbol && strlen(symbol) > 0) {
        if (strcmp(symbol, alertSymbol) != 0 || 
            (millis() - alertStartTime) > 30000) {
          strlcpy(alertSymbol, symbol, 12);
          alertPrice = doc["price"] | 0;
          alertActive = true;
          alertStartTime = millis();
          playMelody(MELODY_ALERT);
        }
      }
    }
  }
  
  http.end();
}

// ============ DISPLAY ============
void updateDisplay() {
  if (alertActive && (millis() - alertStartTime > ALERT_DURATION)) {
    alertActive = false;
  }
  
  if (alertActive) {
    showAlertScreen();
    return;
  }
  
  switch (currentScreen) {
    case SCR_OVERVIEW:
      showOverviewScreen();
      break;
    case SCR_POSITIONS:
      showPositionsScreen();
      break;
    case SCR_STRATEGY:
      showStrategyScreen();
      break;
    case SCR_NETWORK:
      showNetworkScreen();
      break;
  }
}

void showBootScreen() {
  display.clearDisplay();
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.print(F("Trading Bot - "));
  display.println(BOARD_NAME);
  display.println(F("================="));
  display.println();
  display.println(F("- Paper + Live P&L"));
  display.println(F("- Auto WiFi Recon"));
  display.println(F("- Alert System"));
  display.display();
  delay(2000);
  #ifdef ESP8266
  yield();
  #endif
}

void showOverviewScreen() {
  display.clearDisplay();
  
  display.setCursor(0, 0);
  display.print(data.strategy.paperTrading ? F("[PAPER]") : F("[LIVE]"));
  display.setCursor(90, 0);
  display.print(data.marketOpen ? F("OPEN") : F("CLOSED"));
  
  display.drawLine(0, 9, 127, 9, SSD1306_WHITE);
  
  display.setCursor(0, 12);
  display.print(F("Paper: "));
  if (data.daily.paperPnl >= 0) display.print(F("+"));
  display.print(data.daily.paperPnl, 0);
  
  display.setCursor(0, 22);
  display.print(F("Live:  "));
  if (data.daily.livePnl >= 0) display.print(F("+"));
  display.print(data.daily.livePnl, 0);
  
  float totalPnl = data.daily.paperPnl + data.daily.livePnl;
  display.setCursor(0, 32);
  display.print(F("Total: "));
  if (totalPnl >= 0) display.print(F("+"));
  display.print(totalPnl, 0);
  
  display.setCursor(0, 44);
  display.print(F("Pos: "));
  display.print(data.openPositions);
  display.print(F(" Trd: "));
  display.print(data.daily.totalTrades);
  
  display.setCursor(0, 56);
  display.print(data.systemEnabled ? F("Sys: ACTIVE") : F("Sys: PAUSED"));
  
  display.setCursor(110, 56);
  display.print(F("1/4"));
  
  display.display();
}

void showPositionsScreen() {
  display.clearDisplay();
  
  display.setCursor(0, 0);
  display.print(F("POSITIONS ("));
  display.print(positionCount);
  display.print(F(")"));
  display.setCursor(110, 0);
  display.print(F("2/4"));
  
  display.drawLine(0, 9, 127, 9, SSD1306_WHITE);
  
  if (positionCount == 0) {
    display.setCursor(25, 30);
    display.print(F("No positions"));
  } else {
    int maxPos = positionCount;
    #ifdef ESP8266
    if (maxPos > 4) maxPos = 4;
    #else
    if (maxPos > 4) maxPos = 4;
    #endif
    
    for (int i = 0; i < maxPos; i++) {
      int y = 12 + (i * 13);
      
      display.setCursor(0, y);
      display.print(positions[i].symbol);
      display.print(positions[i].isPaper ? F(" P") : F(" L"));
      
      display.setCursor(70, y);
      if (positions[i].pnl >= 0) display.print(F("+"));
      display.print(positions[i].pnl, 0);
      
      display.setCursor(100, y);
      display.print(positions[i].pnlPercent, 1);
      display.print(F("%"));
    }
  }
  
  display.display();
}

void showStrategyScreen() {
  display.clearDisplay();
  
  display.setCursor(0, 0);
  display.print(F("STRATEGY"));
  display.setCursor(110, 0);
  display.print(F("3/4"));
  
  display.drawLine(0, 9, 127, 9, SSD1306_WHITE);
  
  display.setCursor(0, 14);
  display.print(F("Risk: "));
  display.print(data.strategy.riskPercent, 1);
  display.print(F("%"));
  
  display.setCursor(0, 26);
  display.print(F("Min R:R: 1:"));
  display.print(data.strategy.minRR, 0);
  
  display.setCursor(0, 38);
  display.print(F("SL ATR: "));
  display.print(data.strategy.atrSl, 1);
  display.print(F("x"));
  
  display.setCursor(0, 50);
  display.print(F("TP ATR: "));
  display.print(data.strategy.atrTp, 1);
  display.print(F("x"));
  
  display.display();
}

void showNetworkScreen() {
  display.clearDisplay();
  
  display.setCursor(0, 0);
  display.print(F("NETWORK"));
  display.setCursor(110, 0);
  display.print(F("4/4"));
  
  display.drawLine(0, 9, 127, 9, SSD1306_WHITE);
  
  display.setCursor(0, 14);
  display.print(F("WiFi: "));
  if (WiFi.status() == WL_CONNECTED) {
    display.print(F("OK"));
    
    display.setCursor(0, 26);
    display.print(WiFi.localIP());
    
    display.setCursor(0, 38);
    display.print(F("RSSI: "));
    display.print(WiFi.RSSI());
    display.print(F(" dBm"));
  } else {
    display.print(F("DISCONNECTED"));
  }
  
  display.setCursor(0, 52);
  display.print(F("Board: "));
  display.print(BOARD_NAME);
  
  display.display();
}

void showAlertScreen() {
  display.clearDisplay();
  
  bool flash = (millis() / 500) % 2 == 0;
  
  if (flash) {
    display.fillRect(0, 0, 128, 64, SSD1306_WHITE);
    display.setTextColor(SSD1306_BLACK);
  } else {
    display.setTextColor(SSD1306_WHITE);
  }
  
  display.setTextSize(2);
  display.setCursor(10, 10);
  display.print(F("NEW TRADE"));
  
  display.setTextSize(1);
  display.setCursor(20, 35);
  display.print(alertSymbol);
  
  display.setCursor(20, 50);
  display.print(F("@ "));
  display.print(alertPrice, 2);
  
  display.display();
  display.setTextColor(SSD1306_WHITE);
}

// ============ INPUT ============
void handleButton() {
  if (digitalRead(PIN_BUTTON) == LOW) {
    if (!btnPressed && millis() - lastButtonPress > BUTTON_DEBOUNCE) {
      btnPressed = true;
      lastButtonPress = millis();
      nextScreen();
      playMelody(MELODY_BUTTON);
      
      // Visual feedback
      digitalWrite(PIN_LED, LED_ON);
      delay(50);
      #ifdef ESP8266
      yield();
      #endif
      digitalWrite(PIN_LED, LED_OFF);
    }
  } else {
    btnPressed = false;
  }
}

void nextScreen() {
  currentScreen = (Screen)((currentScreen + 1) % SCR_COUNT);
  lastScreenCycle = millis();
  alertActive = false;
}

// ============ SOUND ============
void playMelody(Melody melody) {
  switch (melody) {
    case MELODY_BOOT:
      tone(PIN_BUZZER, 2000, 200);
      delay(200);
      #ifdef ESP8266
      yield();
      #endif
      tone(PIN_BUZZER, 2500, 200);
      delay(200);
      #ifdef ESP8266
      yield();
      #endif
      tone(PIN_BUZZER, 3000, 400);
      delay(400);
      #ifdef ESP8266
      yield();
      #endif
      noTone(PIN_BUZZER);
      break;
      
    case MELODY_BUTTON:
      tone(PIN_BUZZER, 1500, 50);
      delay(50);
      noTone(PIN_BUZZER);
      break;
      
    case MELODY_ALERT:
      for(int i=0; i<3; i++) {
        tone(PIN_BUZZER, 2500, 150);
        delay(200);
        #ifdef ESP8266
        yield();
        #endif
      }
      noTone(PIN_BUZZER);
      break;
      
    case MELODY_SUCCESS:
      tone(PIN_BUZZER, 2000, 100);
      delay(100);
      #ifdef ESP8266
      yield();
      #endif
      tone(PIN_BUZZER, 2500, 100);
      delay(100);
      #ifdef ESP8266
      yield();
      #endif
      tone(PIN_BUZZER, 3000, 300);
      delay(300);
      noTone(PIN_BUZZER);
      break;
      
    case MELODY_ERROR:
      tone(PIN_BUZZER, 1500, 300);
      delay(300);
      #ifdef ESP8266
      yield();
      #endif
      tone(PIN_BUZZER, 1000, 500);
      delay(500);
      noTone(PIN_BUZZER);
      break;
  }
}
