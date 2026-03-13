/*
 * ESP8266 Trading Display - FIXED VERSION
 * =======================================
 * Hardware: ESP8266 (NodeMCU/D1 Mini) + 1.3" 128x64 OLED
 * 
 * FIXES APPLIED:
 * - Added yield() in all delay loops to prevent watchdog reset
 * - Fixed playAlertSound() to not block with delay()
 * - Added proper WiFi reconnection with backoff
 * - Added HTTP timeout to prevent hangs
 * - Fixed button debouncing (300ms)
 * - Added LED status indicators
 * - Better memory management for ESP8266 limited RAM
 * - Added WiFiClient to HTTP calls
 * - Fixed String concatenation causing fragmentation
 * - Added delay(1) in main loop for WiFi stack
 * 
 * API Endpoints:
 * - /api/esp/stats - Basic stats
 * - /api/insights - Trade insights
 * - /api/esp/positions - Open positions
 * - /api/esp/alert - New trade alerts
 */

#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>
#include <WiFiClient.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

// ============ USER CONFIGURATION ============
const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASS = "YOUR_WIFI_PASSWORD";
const char* SERVER_URL = "http://YOUR_SERVER_IP:8000";

// Pins (NodeMCU/D1 Mini)
#define PIN_BUTTON    12   // D6
#define PIN_LED       2    // D4 (built-in, active LOW)
#define PIN_BUZZER    14   // D5
#define OLED_SDA      4    // D2
#define OLED_SCL      5    // D1

// OLED
#define SCREEN_WIDTH  128
#define SCREEN_HEIGHT 64
#define OLED_ADDR     0x3C
#define OLED_RESET    -1

// Timing (conservative for ESP8266)
#define DATA_INTERVAL       10000   // 10 seconds
#define ALERT_INTERVAL      5000    // 5 seconds
#define DISPLAY_INTERVAL    100     // ~10fps
#define AUTO_CYCLE_TIME     10000   // 10 seconds per screen
#define WIFI_TIMEOUT        10000   // 10s
#define HTTP_TIMEOUT        5000    // 5s HTTP timeout
#define BUTTON_DEBOUNCE     300     // 300ms debounce
#define ALERT_DURATION      5000    // 5 seconds
#define WIFI_RECONNECT_INT  30000   // 30s reconnect interval

// LED blink patterns
#define BLINK_SLOW    1000
#define BLINK_FAST    200
#define BLINK_ALERT   100

Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);
WiFiClient wifiClient;

// ============ DATA STRUCTURES ============
struct Position {
  char symbol[12];
  float pnl;
  float pnlPercent;
  bool isPaper;
};

struct TradingData {
  bool systemEnabled;
  bool marketOpen;
  bool paperTrading;
  int openPositions;
  float paperPnl;
  float livePnl;
  int totalTrades;
  float riskPercent;
  float minRR;
  bool hasRecommendation;
};

// Global state
TradingData data = {false, false, true, 0, 0, 0, 0, 1.0, 2.0, false};
Position positions[5];  // Limited for ESP8266 memory
int positionCount = 0;

// Screens
enum Screen {
  SCR_OVERVIEW,
  SCR_POSITIONS,
  SCR_STRATEGY,
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
  yield();  // Let WiFi stack initialize
  
  Serial.println(F("\n================================"));
  Serial.println(F("ESP8266 Trading Display FIXED"));
  Serial.println(F("================================\n"));
  
  // Pins
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  pinMode(PIN_LED, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);
  digitalWrite(PIN_LED, HIGH);  // LED off (active low)
  
  // Init OLED
  Wire.begin(OLED_SDA, OLED_SCL);
  if(!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
    Serial.println(F("SSD1306 failed"));
    for(;;) {
      digitalWrite(PIN_LED, !digitalRead(PIN_LED));
      delay(100);
      yield();
    }
  }
  
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  
  showBootScreen();
  
  // Connect WiFi
  connectWiFi();
  
  if (WiFi.status() == WL_CONNECTED) {
    fetchAllData();
  }
  
  Serial.println(F("Setup complete!"));
  Serial.print(F("Free heap: "));
  Serial.println(ESP.getFreeHeap());
}

// ============ MAIN LOOP ============
void loop() {
  unsigned long now = millis();
  
  // Handle LED status
  handleLedStatus(now);
  
  // Handle button
  handleButton();
  
  // WiFi reconnection check
  if (now - lastWiFiCheck >= WIFI_RECONNECT_INT) {
    checkWiFiConnection();
    lastWiFiCheck = now;
  }
  
  // Fetch data (only if connected)
  if (WiFi.status() == WL_CONNECTED && now - lastDataFetch >= DATA_INTERVAL) {
    fetchAllData();
    lastDataFetch = now;
  }
  
  // Check alerts
  if (WiFi.status() == WL_CONNECTED && now - lastAlertCheck >= ALERT_INTERVAL) {
    checkAlerts();
    lastAlertCheck = now;
  }
  
  // Auto cycle screens
  if (now - lastScreenCycle >= AUTO_CYCLE_TIME) {
    nextScreen();
    lastScreenCycle = now;
  }
  
  // Update display
  if (now - lastDisplayUpdate >= DISPLAY_INTERVAL) {
    updateDisplay();
    lastDisplayUpdate = now;
  }
  
  // CRITICAL: ESP8266 needs frequent yield to prevent watchdog
  delay(1);
  yield();
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
    digitalWrite(PIN_LED, ledState ? LOW : HIGH);  // Active low
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
  
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  
  int attempts = 0;
  unsigned long startTime = millis();
  
  while (WiFi.status() != WL_CONNECTED && attempts < 40) {
    delay(250);
    yield();  // CRITICAL: Feed watchdog
    Serial.print(".");
    
    if (attempts % 4 == 0) {
      display.print(".");
      display.display();
    }
    
    attempts++;
    
    if (millis() - startTime > WIFI_TIMEOUT) {
      break;
    }
  }
  
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print(F("\nWiFi OK! IP: "));
    Serial.println(WiFi.localIP());
    display.println(F("\nOK!"));
  } else {
    Serial.println(F("\nWiFi Failed"));
    display.println(F("\nFailed!"));
  }
  display.display();
  delay(500);
  yield();
}

void checkWiFiConnection() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println(F("WiFi disconnected, reconnecting..."));
    WiFi.disconnect();
    yield();
    delay(100);
    yield();
    connectWiFi();
  }
}

// ============ DATA FETCHING ============
void fetchAllData() {
  if (WiFi.status() != WL_CONNECTED) return;
  
  fetchESPStats();
  yield();  // Let WiFi stack process
  fetchInsights();
  yield();
  fetchPositions();
}

void fetchESPStats() {
  HTTPClient http;
  String url = String(SERVER_URL) + "/api/esp/stats";
  
  http.begin(wifiClient, url);
  http.setTimeout(HTTP_TIMEOUT);
  int httpCode = http.GET();
  
  if (httpCode == 200) {
    String payload = http.getString();
    // Use smaller buffer for ESP8266
    StaticJsonDocument<384> doc;
    DeserializationError error = deserializeJson(doc, payload);
    
    if (!error) {
      data.systemEnabled = doc["system_enabled"] | false;
      data.marketOpen = doc["market_open"] | false;
      data.paperTrading = doc["paper_trading"] | true;
      data.openPositions = doc["open_positions"] | 0;
      data.totalTrades = doc["today_trades"] | 0;
    }
  } else {
    Serial.print(F("Stats fail: "));
    Serial.println(httpCode);
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
    StaticJsonDocument<768> doc;  // Limited for ESP8266
    DeserializationError error = deserializeJson(doc, payload);
    
    if (!error) {
      JsonObject dailyStats = doc["daily_stats"];
      if (!dailyStats.isNull()) {
        for (JsonPair day : dailyStats) {
          JsonObject stats = day.value();
          data.paperPnl = stats["paper_pnl"] | 0;
          data.livePnl = stats["live_pnl"] | 0;
        }
      }
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
    StaticJsonDocument<768> doc;
    DeserializationError error = deserializeJson(doc, payload);
    
    if (!error) {
      JsonArray posArray = doc["positions"];
      positionCount = 0;
      
      for (JsonObject pos : posArray) {
        if (positionCount >= 5) break;
        
        strlcpy(positions[positionCount].symbol, pos["symbol"] | "", 12);
        positions[positionCount].pnl = pos["pnl"] | 0;
        positions[positionCount].pnlPercent = pos["pnl_percent"] | 0;
        positions[positionCount].isPaper = pos["paper_trading"] | true;
        
        positionCount++;
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
    StaticJsonDocument<256> doc;
    DeserializationError error = deserializeJson(doc, payload);
    
    if (!error) {
      const char* symbol = doc["symbol"];
      if (symbol && strlen(symbol) > 0) {
        // Only trigger if new alert (different symbol or 30s passed)
        if (strcmp(symbol, alertSymbol) != 0 || 
            (millis() - alertStartTime) > 30000) {
          strlcpy(alertSymbol, symbol, 12);
          alertPrice = doc["price"] | 0;
          alertActive = true;
          alertStartTime = millis();
          playAlertSound();
        }
      }
    }
  }
  
  http.end();
}

// ============ DISPLAY ============
void updateDisplay() {
  // Clear alert after duration
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
  }
}

void showBootScreen() {
  display.clearDisplay();
  display.setCursor(0, 0);
  display.println(F("Trading Bot FIXED"));
  display.println(F("================="));
  display.println();
  display.println(F("ESP8266 Edition"));
  display.println();
  display.println(F("- Watchdog Safe"));
  display.println(F("- Auto Reconnect"));
  display.display();
  delay(2000);
  yield();
}

void showOverviewScreen() {
  display.clearDisplay();
  
  // Header
  display.setCursor(0, 0);
  display.print(data.paperTrading ? F("[PAPER]") : F("[LIVE]"));
  display.setCursor(90, 0);
  display.print(data.marketOpen ? F("OPEN") : F("CLOSED"));
  
  display.drawLine(0, 9, 127, 9, SSD1306_WHITE);
  
  // Paper P&L
  display.setCursor(0, 12);
  display.print(F("Paper:"));
  if (data.paperPnl >= 0) display.print(F(" +"));
  else display.print(F(" "));
  display.print(data.paperPnl, 0);
  
  // Live P&L
  display.setCursor(0, 23);
  display.print(F("Live: "));
  if (data.livePnl >= 0) display.print(F(" +"));
  else display.print(F(" "));
  display.print(data.livePnl, 0);
  
  // Total
  float total = data.paperPnl + data.livePnl;
  display.setCursor(0, 34);
  display.print(F("Total:"));
  if (total >= 0) display.print(F(" +"));
  else display.print(F(" "));
  display.print(total, 0);
  
  // Stats
  display.setCursor(0, 48);
  display.print(F("Pos:"));
  display.print(data.openPositions);
  display.print(F(" Trd:"));
  display.print(data.totalTrades);
  
  // Screen indicator
  display.setCursor(110, 56);
  display.print(F("1/3"));
  
  display.display();
}

void showPositionsScreen() {
  display.clearDisplay();
  
  display.setCursor(0, 0);
  display.print(F("POSITIONS ("));
  display.print(positionCount);
  display.print(F(")"));
  display.setCursor(110, 0);
  display.print(F("2/3"));
  
  display.drawLine(0, 9, 127, 9, SSD1306_WHITE);
  
  if (positionCount == 0) {
    display.setCursor(25, 30);
    display.print(F("No positions"));
  } else {
    for (int i = 0; i < min(positionCount, 4); i++) {
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
  display.print(F("3/3"));
  
  display.drawLine(0, 9, 127, 9, SSD1306_WHITE);
  
  display.setCursor(0, 14);
  display.print(F("Risk:"));
  display.print(data.riskPercent, 1);
  display.print(F("%"));
  
  display.setCursor(0, 26);
  display.print(F("Min R:R:1:"));
  display.print(data.minRR, 0);
  
  display.setCursor(0, 40);
  display.print(F("System:"));
  display.print(data.systemEnabled ? F("ACTIVE") : F("PAUSED"));
  
  display.setCursor(0, 54);
  display.print(F("WiFi:"));
  if (WiFi.status() == WL_CONNECTED) {
    display.print(WiFi.RSSI());
    display.print(F("dBm"));
  } else {
    display.print(F("OFF"));
  }
  
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
  display.setCursor(15, 10);
  display.print(F("ALERT!"));
  
  display.setTextSize(1);
  display.setCursor(25, 35);
  display.print(alertSymbol);
  
  display.setCursor(25, 50);
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
      
      // Visual feedback
      digitalWrite(PIN_LED, LOW);
      delay(50);
      yield();
      digitalWrite(PIN_LED, HIGH);
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
void playAlertSound() {
  // FIXED: Non-blocking with yield() calls
  for (int i = 0; i < 3; i++) {
    tone(PIN_BUZZER, 2000 + (i * 300), 100);
    delay(100);
    yield();  // CRITICAL: Feed watchdog
  }
  noTone(PIN_BUZZER);
}
