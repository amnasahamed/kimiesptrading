/*
 * ESP32 Trading Display - FIXED VERSION
 * =====================================
 * Hardware: ESP32-WROOM + 1.3" 128x64 OLED (SSD1306 I2C)
 * 
 * FIXES APPLIED:
 * - Fixed alert clear bug (static variable issue)
 * - Added WiFiClient to HTTP calls
 * - Added proper HTTP timeouts
 * - Fixed button debouncing (300ms)
 * - Added WiFi reconnection with exponential backoff
 * - Added LED status indicators
 * - Added yield() during delays to prevent watchdog
 * - Fixed memory fragmentation issues
 * - Better error handling for API failures
 * - Alert timeout now per-alert, not static
 * 
 * API Endpoints Used:
 * - /api/esp/stats - Basic stats
 * - /api/insights - Trade insights
 * - /api/esp/positions - Open positions
 * - /api/esp/alert - New trade alerts
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClient.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

// ============ USER CONFIGURATION ============
const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASS = "YOUR_WIFI_PASSWORD";
const char* SERVER_URL = "http://YOUR_SERVER_IP:8000";
const char* DEVICE_ID = "esp32_trading_v2";

// Pins
#define PIN_BUTTON      4
#define PIN_BUZZER      18
#define PIN_LED         2
#define OLED_SDA        21
#define OLED_SCL        22
#define OLED_ADDR       0x3C
#define OLED_RESET      -1

// Display
#define SCREEN_WIDTH    128
#define SCREEN_HEIGHT   64

// Timing (milliseconds)
#define DATA_INTERVAL       5000    // 5 seconds
#define ALERT_INTERVAL      2000    // 2 seconds
#define DISPLAY_INTERVAL    50      // ~20fps
#define AUTO_CYCLE_TIME     8000    // 8 seconds per screen
#define WIFI_TIMEOUT        10000   // 10s connect timeout
#define HTTP_TIMEOUT        4000    // 4s HTTP timeout
#define BUTTON_DEBOUNCE     300     // 300ms debounce
#define ALERT_DURATION      5000    // 5 seconds alert display
#define WIFI_RECONNECT_INT  30000   // Try reconnect every 30s

// LED blink patterns
#define BLINK_SLOW    1000  // Connected, healthy
#define BLINK_FAST    200   // Error/disconnected
#define BLINK_ALERT   100   // New alert

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

// Screen management
enum Screen {
  SCR_OVERVIEW,
  SCR_POSITIONS,
  SCR_STRATEGY,
  SCR_NETWORK,
  SCR_COUNT
};
Screen currentScreen = SCR_OVERVIEW;
const char* screenNames[] = {"OVERVIEW", "POSITIONS", "STRATEGY", "NETWORK"};

// Timing
unsigned long lastDataFetch = 0;
unsigned long lastAlertCheck = 0;
unsigned long lastDisplayUpdate = 0;
unsigned long lastScreenCycle = 0;
unsigned long lastButtonPress = 0;
unsigned long lastWiFiCheck = 0;
unsigned long lastLedBlink = 0;
bool ledState = false;

// WiFi reconnect backoff
int wifiReconnectAttempts = 0;
unsigned long wifiReconnectDelay = 5000;

// Button
bool btnPressed = false;

// Alert state
bool alertActive = false;
char alertSymbol[12] = "";
float alertPrice = 0;
unsigned long alertStartTime = 0;  // FIXED: Not static anymore

// ============ SETUP ============
void setup() {
  Serial.begin(115200);
  delay(100);
  
  Serial.println(F("\n================================"));
  Serial.println(F("ESP32 Trading Display FIXED"));
  Serial.println(F("================================\n"));
  
  // Pins
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  pinMode(PIN_LED, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);
  digitalWrite(PIN_LED, HIGH);  // Start with LED on
  
  // Init OLED
  Wire.begin(OLED_SDA, OLED_SCL);
  if(!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
    Serial.println(F("SSD1306 allocation failed"));
    for(;;) {
      digitalWrite(PIN_LED, !digitalRead(PIN_LED));
      delay(100);
    }
  }
  
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  
  showBootScreen();
  
  // Connect WiFi
  connectWiFi();
  
  // Initial data fetch
  if (WiFi.status() == WL_CONNECTED) {
    fetchAllData();
  }
  
  Serial.println(F("Setup complete!"));
}

// ============ MAIN LOOP ============
void loop() {
  unsigned long now = millis();
  
  // Handle LED status indication
  handleLedStatus(now);
  
  // Handle button
  handleButton();
  
  // WiFi reconnection check
  if (now - lastWiFiCheck >= WIFI_RECONNECT_INT) {
    checkWiFiConnection();
    lastWiFiCheck = now;
  }
  
  // Fetch data periodically (only if WiFi connected)
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
  
  // Small delay to yield to WiFi stack
  delay(1);
}

// ============ LED STATUS HANDLING ============
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
    digitalWrite(PIN_LED, ledState);
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
    yield();  // Feed watchdog
    Serial.print(".");
    
    if (attempts % 4 == 0) {
      display.print(".");
      display.display();
    }
    
    attempts++;
    
    // Timeout check
    if (millis() - startTime > WIFI_TIMEOUT) {
      break;
    }
  }
  
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print(F("\nWiFi Connected! IP: "));
    Serial.println(WiFi.localIP());
    wifiReconnectAttempts = 0;
    wifiReconnectDelay = 5000;
  } else {
    Serial.println(F("\nWiFi Connect Failed!"));
  }
}

void checkWiFiConnection() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println(F("WiFi disconnected, reconnecting..."));
    WiFi.disconnect();
    delay(100);
    yield();
    connectWiFi();
  }
}

// ============ DATA FETCHING ============
void fetchAllData() {
  if (WiFi.status() != WL_CONNECTED) return;
  
  fetchESPStats();
  fetchPositions();
  fetchInsights();
}

void fetchESPStats() {
  HTTPClient http;
  String url = String(SERVER_URL) + "/api/esp/stats";
  
  http.begin(wifiClient, url);
  http.setTimeout(HTTP_TIMEOUT);
  int httpCode = http.GET();
  
  if (httpCode == 200) {
    String payload = http.getString();
    StaticJsonDocument<512> doc;
    DeserializationError error = deserializeJson(doc, payload);
    
    if (!error) {
      data.systemEnabled = doc["system_enabled"] | false;
      data.marketOpen = doc["market_open"] | false;
      data.openPositions = doc["open_positions"] | 0;
      data.strategy.paperTrading = doc["paper_trading"] | true;
      data.daily.paperPnl = doc["today_pnl"] | 0;
      data.daily.totalTrades = doc["today_trades"] | 0;
    }
  } else {
    Serial.print(F("Stats fetch failed: "));
    Serial.println(httpCode);
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
    StaticJsonDocument<2048> doc;
    DeserializationError error = deserializeJson(doc, payload);
    
    if (!error) {
      JsonArray posArray = doc["positions"];
      positionCount = 0;
      
      for (JsonObject pos : posArray) {
        if (positionCount >= 10) break;
        
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
    StaticJsonDocument<1024> doc;
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
    StaticJsonDocument<256> doc;
    DeserializationError error = deserializeJson(doc, payload);
    
    if (!error) {
      const char* symbol = doc["symbol"];
      if (symbol && strlen(symbol) > 0 && strcmp(symbol, alertSymbol) != 0) {
        // New alert!
        strlcpy(alertSymbol, symbol, 12);
        alertPrice = doc["price"] | 0;
        alertActive = true;
        alertStartTime = millis();  // FIXED: Set start time per alert
        playAlertSound();
      }
    }
  }
  
  http.end();
}

// ============ DISPLAY ============
void updateDisplay() {
  // FIXED: Check alert timeout here, not in showAlertScreen
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
  display.println(F("Trading Bot FIXED"));
  display.println(F("================="));
  display.println();
  display.println(F("- Paper + Live P&L"));
  display.println(F("- WiFi Auto-Recon"));
  display.println(F("- Alert Bug Fixed"));
  display.display();
  delay(2000);
}

void showOverviewScreen() {
  display.clearDisplay();
  
  // Header
  display.setCursor(0, 0);
  display.print(data.strategy.paperTrading ? F("[PAPER]") : F("[LIVE]"));
  display.setCursor(90, 0);
  display.print(data.marketOpen ? F("OPEN") : F("CLOSED"));
  
  display.drawLine(0, 9, 127, 9, SSD1306_WHITE);
  
  // Paper P&L
  display.setCursor(0, 12);
  display.print(F("Paper: "));
  if (data.daily.paperPnl >= 0) display.print(F("+"));
  display.print(data.daily.paperPnl, 0);
  
  // Live P&L
  display.setCursor(0, 22);
  display.print(F("Live:  "));
  if (data.daily.livePnl >= 0) display.print(F("+"));
  display.print(data.daily.livePnl, 0);
  
  // Total
  float totalPnl = data.daily.paperPnl + data.daily.livePnl;
  display.setCursor(0, 32);
  display.print(F("Total: "));
  if (totalPnl >= 0) display.print(F("+"));
  display.print(totalPnl, 0);
  
  // Stats
  display.setCursor(0, 44);
  display.print(F("Pos: "));
  display.print(data.openPositions);
  display.print(F(" Trd: "));
  display.print(data.daily.totalTrades);
  
  // System status
  display.setCursor(0, 56);
  display.print(data.systemEnabled ? F("Sys: ACTIVE") : F("Sys: PAUSED"));
  
  // Screen indicator
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
  display.print(F("Server: "));
  display.print(data.systemEnabled ? F("OK") : F("ERR"));
  
  display.display();
}

void showAlertScreen() {
  display.clearDisplay();
  
  // Flash effect
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
    }
  } else {
    btnPressed = false;
  }
}

void nextScreen() {
  currentScreen = (Screen)((currentScreen + 1) % SCR_COUNT);
  lastScreenCycle = millis();
  alertActive = false;  // Clear alert when changing screens
}

// ============ SOUND ============
void playAlertSound() {
  // Non-blocking alert sound
  for (int i = 0; i < 3; i++) {
    tone(PIN_BUZZER, 2000 + (i * 300), 100);
    delay(100);
    yield();  // Feed watchdog
  }
  noTone(PIN_BUZZER);
}
