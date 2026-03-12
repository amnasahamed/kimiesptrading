/*
 * ESP32 Trading Display v2.0
 * ==========================
 * Enhanced for Strategy Optimizer & Paper Trading
 * 
 * Hardware: ESP32-WROOM + 1.3" 128x64 OLED (SSD1306 I2C)
 * 
 * NEW FEATURES:
 * - Shows Paper + Live P&L separately
 * - Displays strategy recommendations
 * - Trade insights per symbol
 * - Better alert system with patterns
 * - Shows current strategy config
 * - Daily stats tracking
 * 
 * API Endpoints Used:
 * - /api/esp/stats - Basic stats (fallback)
 * - /api/insights - Trade insights
 * - /api/strategy/analytics - Strategy recommendations
 * - /api/positions - Open positions
 * - /api/config - Strategy settings
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

// ============ USER CONFIGURATION ============
const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASS = "YOUR_WIFI_PASSWORD";
const char* SERVER_URL = "http://YOUR_SERVER_IP:8000";  // Change to your server
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

// Timing
#define DATA_INTERVAL       5000    // 5 seconds
#define ALERT_INTERVAL      2000    // 2 seconds
#define DISPLAY_INTERVAL    50      // ~20fps for ESP32
#define AUTO_CYCLE_TIME     8000    // 8 seconds per screen
#define WIFI_TIMEOUT        10000   // 10s WiFi connect timeout

Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

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

struct Recommendation {
  char title[40];
  char message[100];
  char priority[10];  // "HIGH", "MEDIUM", "LOW"
};

struct TradingData {
  bool systemEnabled;
  bool marketOpen;
  int openPositions;
  DailyStats daily;
  StrategyConfig strategy;
  Recommendation recs[3];
  int recCount;
};

// Global state
TradingData data = {false, false, 0, {0, 0, 0, 0, 0}, {1.0, 2.0, 1.5, 3.0, true}, {}, 0};
Position positions[10];
int positionCount = 0;

// Screen management
enum Screen {
  SCR_OVERVIEW,      // Paper/Live P&L + Open positions
  SCR_POSITIONS,     // Detailed position list
  SCR_INSIGHTS,      // Strategy recommendations
  SCR_STRATEGY,      // Current strategy config
  SCR_NETWORK,       // WiFi/Server status
  SCR_COUNT
};
Screen currentScreen = SCR_OVERVIEW;
const char* screenNames[] = {"OVERVIEW", "POSITIONS", "INSIGHTS", "STRATEGY", "NETWORK"};

// Timing
unsigned long lastDataFetch = 0;
unsigned long lastAlertCheck = 0;
unsigned long lastDisplayUpdate = 0;
unsigned long lastScreenCycle = 0;
unsigned long lastButtonPress = 0;

// Button
bool btnPressed = false;

// Alert state
bool alertActive = false;
char alertSymbol[12] = "";
float alertPrice = 0;

// ============ SETUP ============
void setup() {
  Serial.begin(115200);
  delay(100);
  
  Serial.println("\n================================");
  Serial.println("ESP32 Trading Display v2.0");
  Serial.println("================================\n");
  
  // Pins
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  pinMode(PIN_LED, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);
  
  // Init OLED
  Wire.begin(OLED_SDA, OLED_SCL);
  if(!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
    Serial.println(F("SSD1306 allocation failed"));
    for(;;);
  }
  
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  
  showBootScreen();
  
  // Connect WiFi
  connectWiFi();
  
  // Initial data fetch
  fetchAllData();
  
  digitalWrite(PIN_LED, LOW);
  Serial.println("Setup complete!");
}

// ============ MAIN LOOP ============
void loop() {
  unsigned long now = millis();
  
  // Handle button
  handleButton();
  
  // Fetch data periodically
  if (now - lastDataFetch >= DATA_INTERVAL) {
    fetchAllData();
    lastDataFetch = now;
  }
  
  // Check alerts
  if (now - lastAlertCheck >= ALERT_INTERVAL) {
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
}

// ============ WIFI ============
void connectWiFi() {
  display.clearDisplay();
  display.setCursor(0, 0);
  display.println(F("Connecting WiFi..."));
  display.display();
  
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    display.print(".");
    display.display();
    attempts++;
  }
  
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWiFi Connected!");
    Serial.print("IP: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("\nWiFi Failed!");
  }
}

// ============ DATA FETCHING ============
void fetchAllData() {
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
    return;
  }
  
  fetchESPStats();
  fetchPositions();
  fetchInsights();
  fetchStrategyAnalytics();
}

void fetchESPStats() {
  HTTPClient http;
  String url = String(SERVER_URL) + "/api/esp/stats";
  
  http.begin(url);
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
      
      // Daily stats from basic endpoint
      data.daily.paperPnl = doc["today_pnl"] | 0;
      data.daily.totalTrades = doc["today_trades"] | 0;
    }
  }
  
  http.end();
}

void fetchPositions() {
  HTTPClient http;
  String url = String(SERVER_URL) + "/api/esp/positions";
  
  http.begin(url);
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
  
  http.begin(url);
  int httpCode = http.GET();
  
  if (httpCode == 200) {
    String payload = http.getString();
    StaticJsonDocument<2048> doc;
    DeserializationError error = deserializeJson(doc, payload);
    
    if (!error) {
      // Get daily stats
      JsonObject dailyStats = doc["daily_stats"];
      if (!dailyStats.isNull()) {
        // Use most recent day
        for (JsonPair day : dailyStats) {
          JsonObject stats = day.value();
          data.daily.paperPnl = stats["paper_pnl"] | 0;
          data.daily.livePnl = stats["live_pnl"] | 0;
          data.daily.totalTrades = stats["trades"] | 0;
        }
      }
      
      // Get recommendations
      JsonArray recs = doc["recommendations"];
      data.recCount = 0;
      for (JsonObject rec : recs) {
        if (data.recCount >= 3) break;
        
        strlcpy(data.recs[data.recCount].title, rec["title"] | "", 40);
        strlcpy(data.recs[data.recCount].message, rec["message"] | "", 100);
        strlcpy(data.recs[data.recCount].priority, rec["priority"] | "MEDIUM", 10);
        
        data.recCount++;
      }
    }
  }
  
  http.end();
}

void fetchStrategyAnalytics() {
  HTTPClient http;
  String url = String(SERVER_URL) + "/api/strategy/analytics";
  
  http.begin(url);
  int httpCode = http.GET();
  
  if (httpCode == 200) {
    String payload = http.getString();
    StaticJsonDocument<1024> doc;
    DeserializationError error = deserializeJson(doc, payload);
    
    if (!error) {
      // Could extract more analytics here if needed
      // For now, we get recommendations from /api/insights
    }
  }
  
  http.end();
}

void checkAlerts() {
  // Check for new alert
  HTTPClient http;
  String url = String(SERVER_URL) + "/api/esp/alert";
  
  http.begin(url);
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
        playAlertSound();
      }
    }
  }
  
  http.end();
}

// ============ DISPLAY ============
void updateDisplay() {
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
    case SCR_NETWORK:
      showNetworkScreen();
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
  display.println(F("Features:"));
  display.println(F("- Paper + Live"));
  display.println(F("- AI Insights"));
  display.println(F("- Strategy Opt"));
  display.display();
  delay(2000);
}

void showOverviewScreen() {
  display.clearDisplay();
  display.setTextSize(1);
  
  // Header
  display.setCursor(0, 0);
  display.print(data.strategy.paperTrading ? "[PAPER MODE]" : "[LIVE MODE]");
  display.setCursor(90, 0);
  display.print(data.marketOpen ? "OPEN" : "CLOSED");
  
  display.drawLine(0, 9, 127, 9, SSD1306_WHITE);
  
  // Paper P&L
  display.setCursor(0, 12);
  display.print("Paper: ");
  if (data.daily.paperPnl >= 0) {
    display.print("+");
  }
  display.print(data.daily.paperPnl, 0);
  display.print(" (");
  display.print(data.daily.paperTrades);
  display.print(")");
  
  // Live P&L
  display.setCursor(0, 22);
  display.print("Live:  ");
  if (data.daily.livePnl >= 0) {
    display.print("+");
  }
  display.print(data.daily.livePnl, 0);
  display.print(" (");
  display.print(data.daily.liveTrades);
  display.print(")");
  
  // Combined
  float totalPnl = data.daily.paperPnl + data.daily.livePnl;
  display.setCursor(0, 32);
  display.print("Total: ");
  if (totalPnl >= 0) {
    display.print("+");
    display.setTextColor(SSD1306_WHITE);
  } else {
    display.setTextColor(SSD1306_WHITE);  // Could use inverse for red
  }
  display.print(totalPnl, 0);
  
  display.setTextColor(SSD1306_WHITE);
  
  // Open positions
  display.setCursor(0, 44);
  display.print("Positions: ");
  display.print(data.openPositions);
  
  // System status
  display.setCursor(0, 56);
  if (data.systemEnabled) {
    display.print("System: ACTIVE");
  } else {
    display.print("System: PAUSED");
  }
  
  // Screen indicator
  display.setCursor(110, 56);
  display.print("1/5");
  
  display.display();
}

void showPositionsScreen() {
  display.clearDisplay();
  display.setTextSize(1);
  
  // Header
  display.setCursor(0, 0);
  display.print(F("OPEN POSITIONS ("));
  display.print(positionCount);
  display.print(F(")"));
  display.setCursor(110, 0);
  display.print("2/5");
  
  display.drawLine(0, 9, 127, 9, SSD1306_WHITE);
  
  if (positionCount == 0) {
    display.setCursor(20, 30);
    display.print(F("No positions"));
  } else {
    // Show up to 4 positions
    for (int i = 0; i < min(positionCount, 4); i++) {
      int y = 12 + (i * 13);
      
      // Symbol + mode indicator
      display.setCursor(0, y);
      display.print(positions[i].symbol);
      if (positions[i].isPaper) {
        display.print(" P");
      } else {
        display.print(" L");
      }
      
      // P&L
      display.setCursor(70, y);
      if (positions[i].pnl >= 0) {
        display.print("+");
      }
      display.print(positions[i].pnl, 0);
      
      // Percent
      display.setCursor(100, y);
      display.print(positions[i].pnlPercent, 1);
      display.print("%");
    }
  }
  
  display.display();
}

void showInsightsScreen() {
  display.clearDisplay();
  display.setTextSize(1);
  
  // Header
  display.setCursor(0, 0);
  display.print(F("AI RECOMMENDATIONS"));
  display.setCursor(110, 0);
  display.print("3/5");
  
  display.drawLine(0, 9, 127, 9, SSD1306_WHITE);
  
  if (data.recCount == 0) {
    display.setCursor(10, 25);
    display.print(F("No recommendations"));
    display.setCursor(10, 35);
    display.print(F("yet. Keep trading!"));
  } else {
    // Show first recommendation
    display.setCursor(0, 12);
    
    // Priority indicator
    if (strcmp(data.recs[0].priority, "HIGH") == 0) {
      display.print("[!] ");
    } else if (strcmp(data.recs[0].priority, "MEDIUM") == 0) {
      display.print("[?] ");
    } else {
      display.print("[i] ");
    }
    
    // Title (truncated)
    char title[20];
    strncpy(title, data.recs[0].title, 19);
    title[19] = '\0';
    display.print(title);
    
    // Message (wrapped)
    display.setCursor(0, 24);
    String msg = String(data.recs[0].message);
    // Simple word wrap
    int line = 0;
    int pos = 0;
    while (pos < msg.length() && line < 3) {
      String chunk = msg.substring(pos, min(pos + 21, msg.length()));
      display.setCursor(0, 24 + (line * 10));
      display.print(chunk);
      pos += 21;
      line++;
    }
    
    // Count indicator
    display.setCursor(0, 56);
    display.print("+");
    display.print(data.recCount - 1);
    display.print(" more in app");
  }
  
  display.display();
}

void showStrategyScreen() {
  display.clearDisplay();
  display.setTextSize(1);
  
  // Header
  display.setCursor(0, 0);
  display.print(F("STRATEGY CONFIG"));
  display.setCursor(110, 0);
  display.print("4/5");
  
  display.drawLine(0, 9, 127, 9, SSD1306_WHITE);
  
  // Config values
  display.setCursor(0, 14);
  display.print("Risk: ");
  display.print(data.strategy.riskPercent, 1);
  display.print("%");
  
  display.setCursor(0, 26);
  display.print("Min R:R: 1:");
  display.print(data.strategy.minRR, 0);
  
  display.setCursor(0, 38);
  display.print("SL ATR: ");
  display.print(data.strategy.atrSl, 1);
  display.print("x");
  
  display.setCursor(0, 50);
  display.print("TP ATR: ");
  display.print(data.strategy.atrTp, 1);
  display.print("x");
  
  display.display();
}

void showNetworkScreen() {
  display.clearDisplay();
  display.setTextSize(1);
  
  // Header
  display.setCursor(0, 0);
  display.print(F("NETWORK STATUS"));
  display.setCursor(110, 0);
  display.print("5/5");
  
  display.drawLine(0, 9, 127, 9, SSD1306_WHITE);
  
  // WiFi info
  display.setCursor(0, 14);
  display.print("WiFi: ");
  if (WiFi.status() == WL_CONNECTED) {
    display.print("OK");
    
    display.setCursor(0, 26);
    display.print("IP: ");
    String ip = WiFi.localIP().toString();
    char ipStr[16];
    ip.toCharArray(ipStr, 16);
    display.print(ipStr);
    
    display.setCursor(0, 38);
    display.print("RSSI: ");
    display.print(WiFi.RSSI());
    display.print(" dBm");
  } else {
    display.print("DISCONNECTED");
  }
  
  // Server
  display.setCursor(0, 52);
  display.print("Server: ");
  display.print(data.systemEnabled ? "OK" : "ERR");
  
  display.display();
}

void showAlertScreen() {
  display.clearDisplay();
  display.setTextSize(2);
  
  // Flash effect
  if ((millis() / 500) % 2 == 0) {
    display.fillRect(0, 0, 128, 64, SSD1306_WHITE);
    display.setTextColor(SSD1306_BLACK);
  } else {
    display.setTextColor(SSD1306_WHITE);
  }
  
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
  
  // Clear alert after 5 seconds
  static unsigned long alertStart = 0;
  if (alertStart == 0) alertStart = millis();
  if (millis() - alertStart > 5000) {
    alertActive = false;
    alertStart = 0;
  }
}

// ============ INPUT HANDLING ============
void handleButton() {
  if (digitalRead(PIN_BUTTON) == LOW) {
    if (!btnPressed && millis() - lastButtonPress > 200) {
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
  
  // Reset alert if any
  alertActive = false;
}

// ============ SOUNDS ============
void playAlertSound() {
  // Simple beep pattern
  tone(PIN_BUZZER, 2000, 100);
  delay(100);
  tone(PIN_BUZZER, 2500, 100);
  delay(100);
  tone(PIN_BUZZER, 3000, 200);
}
