/*
 * ESP8266 Trading Display v2.0
 * ============================
 * Optimized for Strategy Optimizer & Paper Trading
 * 
 * Hardware: ESP8266 (NodeMCU/D1 Mini) + 1.3" 128x64 OLED
 * 
 * NEW FEATURES:
 * - Shows Paper + Live P&L separately
 * - Displays top recommendation
 * - Trade insights
 * - Shows current strategy config
 * - Optimized for ESP8266 memory constraints
 * 
 * API Endpoints Used:
 * - /api/esp/stats - Basic stats
 * - /api/insights - Trade insights & recommendations
 * - /api/esp/positions - Open positions
 */

#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>
#include <WiFiClientSecure.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

// ============ USER CONFIGURATION ============
const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASS = "YOUR_WIFI_PASSWORD";
const char* SERVER_URL = "http://YOUR_SERVER_IP:8000";  // Change to your server

// Pins (NodeMCU/D1 Mini)
#define PIN_BUTTON    12   // D6 - External button
#define PIN_LED       2    // D4 - Built-in LED (active LOW)
#define PIN_BUZZER    14   // D5 - Optional buzzer
#define OLED_SDA      4    // D2
#define OLED_SCL      5    // D1

// OLED
#define SCREEN_WIDTH  128
#define SCREEN_HEIGHT 64
#define OLED_ADDR     0x3C
#define OLED_RESET    -1

// Timing - ESP8266 needs more conservative timing
#define DATA_INTERVAL     8000    // 8 seconds
#define ALERT_INTERVAL    3000    // 3 seconds
#define DISPLAY_INTERVAL  100     // ~10fps (ESP8266 can't handle 30fps with network)
#define AUTO_CYCLE_TIME   10000   // 10 seconds per screen

Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

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
  
  // Strategy config
  float riskPercent;
  float minRR;
  
  // Top recommendation
  bool hasRecommendation;
  char recTitle[30];
  char recPriority[10];
};

// Global state
TradingData data = {false, false, true, 0, 0, 0, 0, 1.0, 2.0, false, "", ""};
Position positions[5];  // Limited for memory
int positionCount = 0;

// Screens
enum Screen {
  SCR_OVERVIEW,
  SCR_POSITIONS,
  SCR_INSIGHTS,
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
  
  Serial.println("\n================================");
  Serial.println("ESP8266 Trading Display v2.0");
  Serial.println("================================\n");
  
  // Pins
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  pinMode(PIN_LED, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);
  digitalWrite(PIN_LED, HIGH);  // LED off (active low)
  
  // Init OLED
  Wire.begin(OLED_SDA, OLED_SCL);
  if(!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
    Serial.println(F("SSD1306 failed"));
    for(;;);
  }
  
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  
  showBootScreen();
  connectWiFi();
  
  Serial.println("Setup complete!");
  Serial.print("Free heap: ");
  Serial.println(ESP.getFreeHeap());
}

// ============ MAIN LOOP ============
void loop() {
  unsigned long now = millis();
  
  handleButton();
  
  if (now - lastDataFetch >= DATA_INTERVAL) {
    fetchAllData();
    lastDataFetch = now;
  }
  
  if (now - lastAlertCheck >= ALERT_INTERVAL) {
    checkAlerts();
    lastAlertCheck = now;
  }
  
  if (now - lastScreenCycle >= AUTO_CYCLE_TIME) {
    nextScreen();
    lastScreenCycle = now;
  }
  
  if (now - lastDisplayUpdate >= DISPLAY_INTERVAL) {
    updateDisplay();
    lastDisplayUpdate = now;
  }
}

// ============ WIFI ============
void connectWiFi() {
  display.clearDisplay();
  display.setCursor(0, 0);
  display.println(F("Connecting WiFi..."));
  display.display();
  
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 30) {
    delay(500);
    Serial.print(".");
    display.print(".");
    display.display();
    attempts++;
  }
  
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWiFi OK");
    display.println("\nOK!");
  } else {
    Serial.println("\nWiFi Failed");
    display.println("\nFailed!");
  }
  display.display();
  delay(1000);
}

// ============ DATA FETCHING ============
void fetchAllData() {
  if (WiFi.status() != WL_CONNECTED) {
    if (WiFi.status() == WL_DISCONNECTED) {
      connectWiFi();
    }
    return;
  }
  
  fetchESPStats();
  fetchInsights();
  fetchPositions();
}

void fetchESPStats() {
  WiFiClient client;
  HTTPClient http;
  String url = String(SERVER_URL) + "/api/esp/stats";
  
  http.begin(client, url);
  http.setTimeout(5000);
  int httpCode = http.GET();
  
  if (httpCode == 200) {
    String payload = http.getString();
    StaticJsonDocument<384> doc;  // Small doc for ESP8266
    DeserializationError error = deserializeJson(doc, payload);
    
    if (!error) {
      data.systemEnabled = doc["system_enabled"] | false;
      data.marketOpen = doc["market_open"] | false;
      data.paperTrading = doc["paper_trading"] | true;
      data.openPositions = doc["open_positions"] | 0;
      data.totalTrades = doc["today_trades"] | 0;
      // We'll get separate paper/live P&L from insights
    }
  }
  
  http.end();
}

void fetchInsights() {
  WiFiClient client;
  HTTPClient http;
  String url = String(SERVER_URL) + "/api/insights";
  
  http.begin(client, url);
  http.setTimeout(5000);
  int httpCode = http.GET();
  
  if (httpCode == 200) {
    String payload = http.getString();
    StaticJsonDocument<1024> doc;  // Limited size for ESP8266
    DeserializationError error = deserializeJson(doc, payload);
    
    if (!error) {
      // Get daily stats - use most recent
      JsonObject dailyStats = doc["daily_stats"];
      if (!dailyStats.isNull()) {
        // Iterate to get last entry
        for (JsonPair day : dailyStats) {
          JsonObject stats = day.value();
          data.paperPnl = stats["paper_pnl"] | 0;
          data.livePnl = stats["live_pnl"] | 0;
        }
      }
      
      // Get top recommendation
      JsonArray recs = doc["recommendations"];
      if (recs.size() > 0) {
        data.hasRecommendation = true;
        JsonObject rec = recs[0];
        strlcpy(data.recTitle, rec["title"] | "No title", 30);
        strlcpy(data.recPriority, rec["priority"] | "MEDIUM", 10);
      } else {
        data.hasRecommendation = false;
      }
    }
  }
  
  http.end();
}

void fetchPositions() {
  WiFiClient client;
  HTTPClient http;
  String url = String(SERVER_URL) + "/api/esp/positions";
  
  http.begin(client, url);
  http.setTimeout(5000);
  int httpCode = http.GET();
  
  if (httpCode == 200) {
    String payload = http.getString();
    StaticJsonDocument<1024> doc;
    DeserializationError error = deserializeJson(doc, payload);
    
    if (!error) {
      JsonArray posArray = doc["positions"];
      positionCount = 0;
      
      for (JsonObject pos : posArray) {
        if (positionCount >= 5) break;  // Limited for ESP8266
        
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
  WiFiClient client;
  HTTPClient http;
  String url = String(SERVER_URL) + "/api/esp/alert";
  
  http.begin(client, url);
  http.setTimeout(2000);
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
  // Auto-clear alert after 5 seconds
  if (alertActive && (millis() - alertStartTime) > 5000) {
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
    case SCR_INSIGHTS:
      showInsightsScreen();
      break;
    case SCR_STRATEGY:
      showStrategyScreen();
      break;
  }
}

void showBootScreen() {
  display.clearDisplay();
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.println(F("Trading Bot v2.0"));
  display.println(F("================"));
  display.println();
  display.println(F("ESP8266 Edition"));
  display.println();
  display.println(F("Features:"));
  display.println(F("Paper+LIVE"));
  display.println(F("AI Insights"));
  display.display();
  delay(2000);
}

void showOverviewScreen() {
  display.clearDisplay();
  
  // Header with mode
  display.setCursor(0, 0);
  if (data.paperTrading) {
    display.print(F("[PAPER MODE]"));
  } else {
    display.print(F("[LIVE MODE]"));
  }
  
  // Market status
  display.setCursor(90, 0);
  if (data.marketOpen) {
    display.print(F("OPEN"));
  } else {
    display.print(F("CLOSED"));
  }
  
  display.drawLine(0, 9, 127, 9, SSD1306_WHITE);
  
  // Paper P&L
  display.setCursor(0, 12);
  display.print(F("Paper:"));
  if (data.paperPnl >= 0) {
    display.print(F(" +"));
  } else {
    display.print(F(" "));
  }
  display.print(data.paperPnl, 0);
  
  // Live P&L
  display.setCursor(0, 23);
  display.print(F("Live: "));
  if (data.livePnl >= 0) {
    display.print(F(" +"));
  } else {
    display.print(F(" "));
  }
  display.print(data.livePnl, 0);
  
  // Total
  float total = data.paperPnl + data.livePnl;
  display.setCursor(0, 34);
  display.print(F("Total:"));
  if (total >= 0) {
    display.print(F(" +"));
  } else {
    display.print(F(" "));
  }
  display.print(total, 0);
  
  // Stats
  display.setCursor(0, 48);
  display.print(F("Pos:"));
  display.print(data.openPositions);
  display.print(F(" Trd:"));
  display.print(data.totalTrades);
  
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
      
      // Mode indicator
      if (positions[i].isPaper) {
        display.print(F(" P"));
      } else {
        display.print(F(" L"));
      }
      
      // P&L
      display.setCursor(70, y);
      if (positions[i].pnl >= 0) {
        display.print(F("+"));
      }
      display.print(positions[i].pnl, 0);
      
      // Percent
      display.setCursor(100, y);
      display.print(positions[i].pnlPercent, 1);
      display.print(F("%"));
    }
  }
  
  display.display();
}

void showInsightsScreen() {
  display.clearDisplay();
  
  display.setCursor(0, 0);
  display.print(F("AI INSIGHTS"));
  display.setCursor(110, 0);
  display.print(F("3/4"));
  
  display.drawLine(0, 9, 127, 9, SSD1306_WHITE);
  
  if (!data.hasRecommendation) {
    display.setCursor(15, 25);
    display.print(F("No recommendations"));
    display.setCursor(25, 40);
    display.print(F("Keep trading!"));
  } else {
    display.setCursor(0, 12);
    
    // Priority icon
    if (strcmp(data.recPriority, "HIGH") == 0) {
      display.print(F("[!] "));
    } else if (strcmp(data.recPriority, "MEDIUM") == 0) {
      display.print(F("[?] "));
    } else {
      display.print(F("[i] "));
    }
    
    // Title (truncated)
    char title[17];
    strncpy(title, data.recTitle, 16);
    title[16] = '\0';
    display.print(title);
    
    // More in app
    display.setCursor(0, 56);
    display.print(F("More in dashboard"));
  }
  
  display.display();
}

void showStrategyScreen() {
  display.clearDisplay();
  
  display.setCursor(0, 0);
  display.print(F("STRATEGY"));
  display.setCursor(110, 0);
  display.print(F("4/4"));
  
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
  if (data.systemEnabled) {
    display.print(F("ACTIVE"));
  } else {
    display.print(F("PAUSED"));
  }
  
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
  
  // Flash effect
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
    if (!btnPressed && millis() - lastButtonPress > 200) {
      btnPressed = true;
      lastButtonPress = millis();
      nextScreen();
      
      // Visual feedback
      digitalWrite(PIN_LED, LOW);
      delay(50);
      digitalWrite(PIN_LED, HIGH);
    }
  } else {
    btnPressed = false;
  }
}

void nextScreen() {
  currentScreen = (Screen)((currentScreen + 1) % SCR_COUNT);
  lastScreenCycle = millis();
}

// ============ SOUND ============
void playAlertSound() {
  // Simple tones
  tone(PIN_BUZZER, 2000, 150);
  delay(150);
  tone(PIN_BUZZER, 2500, 150);
  delay(150);
  noTone(PIN_BUZZER);
}
