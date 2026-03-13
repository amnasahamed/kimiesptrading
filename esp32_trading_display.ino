/*
 * ESP32-WROOM Trading Display - ENHANCED VERSION
 * ================================================
 * For: Melon Trading Bot
 * Board: ESP32-WROOM-32 (4MB Flash, 520KB SRAM)
 * Display: ILI9341 2.4" TFT (240x320) or SSD1309 OLED (128x64)
 * 
 * Features:
 * - Color graphics and animations
 * - Progress bars for SL/TP
 * - Multiple screen layouts
 * - Touch support (if using TFT)
 * - SD card logging
 * - OTA updates
 * - Better WiFi handling
 * - More position data
 * - Trade history scroll
 * - Alert sounds via buzzer
 * 
 * Pinout for ESP32:
 * - TFT_CS:    GPIO 5
 * - TFT_DC:    GPIO 16
 * - TFT_RST:   GPIO 17
 * - TFT_MOSI:  GPIO 23
 * - TFT_SCK:   GPIO 18
 * - TFT_MISO:  GPIO 19
 * - SD_CS:     GPIO 4
 * - BUZZER:    GPIO 25
 * - BUTTON_1:  GPIO 26
 * - BUTTON_2:  GPIO 27
 * - LED_R:     GPIO 32
 * - LED_G:     GPIO 33
 * - LED_B:     GPIO 14
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <SPIFFS.h>
#include <ArduinoOTA.h>
#include <SD.h>

// Display libraries - uncomment based on your display
#include <TFT_eSPI.h>           // For ILI9341 TFT (2.4" color display)
// #include <Wire.h>
// #include <Adafruit_SSD1306.h>  // For OLED (monochrome)

// ============== CONFIGURATION ==============
const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASS = "YOUR_WIFI_PASSWORD";
const char* SERVER_URL = "http://192.168.1.100:8000";  // Your trading bot IP
const char* DEVICE_ID = "esp32_trading_display_01";

// Update interval (milliseconds)
const unsigned long UPDATE_INTERVAL = 2000;  // 2 seconds (faster than ESP8266)
const unsigned long DISPLAY_CYCLE_INTERVAL = 5000;  // 5 seconds per screen

// Pin definitions
#define PIN_BUZZER      25
#define PIN_BTN_1       26
#define PIN_BTN_2       27
#define PIN_LED_R       32
#define PIN_LED_G       33
#define PIN_LED_B       14
#define PIN_SD_CS       4

// ============== GLOBAL OBJECTS ==============
TFT_eSPI tft = TFT_eSPI();
// Adafruit_SSD1306 display(128, 64, &Wire, -1);

WiFiClient client;
HTTPClient http;

// ============== DATA STRUCTURES ==============
struct Position {
  String symbol;
  float entryPrice;
  float ltp;
  float sl;
  float tp;
  int quantity;
  float pnl;
  float pnlPercent;
  String entryTime;
  bool isExternal;
};

struct SystemStatus {
  bool tradingEnabled;
  bool paperTrading;
  float capital;
  float todayPnl;
  int openPositions;
  int totalTrades;
  float winRate;
  bool marketOpen;
  String lastUpdate;
};

struct TradeAlert {
  String time;
  String symbol;
  String type;      // "BUY", "SELL", "SL_HIT", "TP_HIT"
  String message;
  float price;
  float pnl;
};

// ============== GLOBAL VARIABLES ==============
Position positions[10];           // Store up to 10 positions
int numPositions = 0;
SystemStatus status;
TradeAlert alerts[20];            // Trade history ring buffer
int alertIndex = 0;
int alertCount = 0;

unsigned long lastUpdate = 0;
unsigned long lastDisplayCycle = 0;
int currentScreen = 0;
const int NUM_SCREENS = 4;

bool wifiConnected = false;
String errorMessage = "";

// ============== SETUP ==============
void setup() {
  Serial.begin(115200);
  delay(100);
  
  Serial.println("\n========================================");
  Serial.println("  ESP32 Trading Display - ENHANCED");
  Serial.println("========================================");
  
  // Initialize pins
  pinMode(PIN_BUZZER, OUTPUT);
  pinMode(PIN_BTN_1, INPUT_PULLUP);
  pinMode(PIN_BTN_2, INPUT_PULLUP);
  pinMode(PIN_LED_R, OUTPUT);
  pinMode(PIN_LED_G, OUTPUT);
  pinMode(PIN_LED_B, OUTPUT);
  
  // Initialize display
  initDisplay();
  
  // Show boot screen
  showBootScreen();
  
  // Initialize SPIFFS for caching
  if (!SPIFFS.begin(true)) {
    Serial.println("SPIFFS mount failed");
  }
  
  // Initialize SD card for logging (optional)
  initSDCard();
  
  // Connect to WiFi
  connectWiFi();
  
  // Setup OTA
  setupOTA();
  
  // Success beep
  playBeep(1000, 100);
  delay(100);
  playBeep(1500, 100);
  
  Serial.println("Setup complete!");
}

// ============== MAIN LOOP ==============
void loop() {
  // Handle OTA updates
  ArduinoOTA.handle();
  
  // Check WiFi and reconnect if needed
  if (WiFi.status() != WL_CONNECTED) {
    wifiConnected = false;
    digitalWrite(PIN_LED_R, HIGH);
    connectWiFi();
  } else {
    wifiConnected = true;
    digitalWrite(PIN_LED_R, LOW);
  }
  
  // Fetch data from server
  unsigned long now = millis();
  if (now - lastUpdate >= UPDATE_INTERVAL) {
    lastUpdate = now;
    fetchTradingData();
    updateLEDs();
  }
  
  // Cycle through screens
  if (now - lastDisplayCycle >= DISPLAY_CYCLE_INTERVAL) {
    lastDisplayCycle = now;
    if (numPositions > 0) {
      currentScreen = (currentScreen + 1) % NUM_SCREENS;
    }
  }
  
  // Handle button presses
  handleButtons();
  
  // Render current screen
  renderScreen();
  
  delay(50);  // Small delay to prevent watchdog issues
}

// ============== DISPLAY INITIALIZATION ==============
void initDisplay() {
  tft.init();
  tft.setRotation(1);  // Landscape
  tft.fillScreen(TFT_BLACK);
  tft.setTextFont(2);
  
  Serial.println("TFT Display initialized: 240x320");
}

// ============== BOOT SCREEN ==============
void showBootScreen() {
  tft.fillScreen(TFT_BLACK);
  
  // Draw border
  tft.drawRect(5, 5, 310, 230, TFT_PRIMARY);
  tft.drawRect(6, 6, 308, 228, TFT_PRIMARY);
  
  // Title
  tft.setTextColor(TFT_PRIMARY, TFT_BLACK);
  tft.setTextSize(2);
  tft.setTextDatum(MC_DATUM);
  tft.drawString("MELON TRADING BOT", 160, 60);
  
  tft.setTextSize(1);
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.drawString("ESP32-WROOM Enhanced Edition", 160, 90);
  
  // Loading animation
  for (int i = 0; i < 100; i += 5) {
    int x = map(i, 0, 100, 40, 280);
    tft.fillRect(40, 150, x - 40, 10, TFT_PRIMARY);
    tft.drawRect(40, 150, 240, 10, TFT_WHITE);
    delay(20);
  }
  
  tft.setTextColor(TFT_GREEN, TFT_BLACK);
  tft.drawString("System Ready!", 160, 190);
  delay(500);
}

// ============== WIFI CONNECTION ==============
void connectWiFi() {
  Serial.print("Connecting to WiFi");
  tft.fillScreen(TFT_BLACK);
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setTextDatum(MC_DATUM);
  tft.drawString("Connecting to WiFi...", 160, 100);
  
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 30) {
    delay(500);
    Serial.print(".");
    attempts++;
    
    // Show progress
    tft.fillRect(40, 130, attempts * 8, 10, TFT_PRIMARY);
    tft.drawRect(40, 130, 240, 10, TFT_WHITE);
  }
  
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWiFi connected!");
    Serial.print("IP: ");
    Serial.println(WiFi.localIP());
    
    wifiConnected = true;
    tft.setTextColor(TFT_GREEN, TFT_BLACK);
    tft.drawString("WiFi Connected!", 160, 160);
    tft.setTextColor(TFT_WHITE, TFT_BLACK);
    tft.drawString(WiFi.localIP().toString(), 160, 180);
    delay(1000);
  } else {
    Serial.println("\nWiFi connection failed!");
    wifiConnected = false;
    errorMessage = "WiFi Failed";
  }
}

// ============== SD CARD INITIALIZATION ==============
void initSDCard() {
  if (!SD.begin(PIN_SD_CS)) {
    Serial.println("SD card initialization failed!");
    return;
  }
  
  Serial.println("SD card initialized");
  
  // Create log file if doesn't exist
  if (!SD.exists("/trades.csv")) {
    File file = SD.open("/trades.csv", FILE_WRITE);
    if (file) {
      file.println("Time,Symbol,Type,Price,PnL");
      file.close();
    }
  }
}

// ============== OTA SETUP ==============
void setupOTA() {
  ArduinoOTA.setHostname("trading-display-esp32");
  
  ArduinoOTA.onStart([]() {
    tft.fillScreen(TFT_BLACK);
    tft.setTextColor(TFT_WHITE, TFT_BLACK);
    tft.setTextDatum(MC_DATUM);
    tft.drawString("OTA Update Starting...", 160, 120);
  });
  
  ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
    int pct = (progress / (total / 100));
    tft.fillRect(40, 140, pct * 2.4, 10, TFT_PRIMARY);
    tft.drawRect(40, 140, 240, 10, TFT_WHITE);
  });
  
  ArduinoOTA.onEnd([]() {
    tft.setTextColor(TFT_GREEN, TFT_BLACK);
    tft.drawString("Update Complete!", 160, 160);
  });
  
  ArduinoOTA.begin();
  Serial.println("OTA ready");
}

// ============== FETCH TRADING DATA ==============
void fetchTradingData() {
  if (!wifiConnected) return;
  
  String url = String(SERVER_URL) + "/api/positions?device=" + DEVICE_ID;
  
  http.begin(client, url);
  http.setTimeout(3000);
  int httpCode = http.GET();
  
  if (httpCode == 200) {
    String payload = http.getString();
    parseTradingData(payload);
    errorMessage = "";
  } else {
    Serial.printf("HTTP error: %d\n", httpCode);
    errorMessage = "API Error: " + String(httpCode);
  }
  
  http.end();
}

// ============== PARSE JSON DATA ==============
void parseTradingData(String json) {
  StaticJsonDocument<4096> doc;  // Larger buffer for ESP32
  DeserializationError error = deserializeJson(doc, json);
  
  if (error) {
    Serial.print("JSON parse failed: ");
    Serial.println(error.c_str());
    return;
  }
  
  // Parse positions
  numPositions = 0;
  JsonArray posArray = doc["positions"].as<JsonArray>();
  for (JsonObject pos : posArray) {
    if (numPositions >= 10) break;
    
    positions[numPositions].symbol = pos["symbol"] | "UNKNOWN";
    positions[numPositions].entryPrice = pos["entry_price"] | 0.0;
    positions[numPositions].ltp = pos["ltp"] | positions[numPositions].entryPrice;
    positions[numPositions].sl = pos["sl_price"] | 0.0;
    positions[numPositions].tp = pos["tp_price"] | 0.0;
    positions[numPositions].quantity = pos["quantity"] | 0;
    positions[numPositions].pnl = pos["unrealized_pnl"] | 0.0;
    positions[numPositions].pnlPercent = pos["pnl_percent"] | 0.0;
    positions[numPositions].isExternal = pos["external"] | false;
    
    numPositions++;
  }
  
  // Parse system status
  status.tradingEnabled = doc["config"]["system_enabled"] | false;
  status.paperTrading = doc["config"]["paper_trading"] | true;
  status.capital = doc["config"]["capital"] | 100000.0;
  status.todayPnl = doc["stats"]["today_pnl"] | 0.0;
  status.openPositions = numPositions;
  status.totalTrades = doc["stats"]["today_trades"] | 0;
  status.winRate = doc["stats"]["win_rate"] | 0.0;
  status.marketOpen = doc["stats"]["within_trading_hours"] | false;
  
  // Check for new alerts/trades
  JsonArray trades = doc["recent_trades"].as<JsonArray>();
  for (JsonObject trade : trades) {
    addAlert(
      trade["symbol"] | "",
      trade["action"] | "",
      trade["message"] | "",
      trade["price"] | 0.0,
      trade["pnl"] | 0.0
    );
  }
}

// ============== ADD ALERT TO HISTORY ==============
void addAlert(String symbol, String type, String message, float price, float pnl) {
  alerts[alertIndex].time = String(millis() / 1000);
  alerts[alertIndex].symbol = symbol;
  alerts[alertIndex].type = type;
  alerts[alertIndex].message = message;
  alerts[alertIndex].price = price;
  alerts[alertIndex].pnl = pnl;
  
  alertIndex = (alertIndex + 1) % 20;
  if (alertCount < 20) alertCount++;
  
  // Log to SD card
  logTradeToSD(symbol, type, price, pnl);
  
  // Play sound for important alerts
  if (type == "BUY" || type == "SELL") {
    playBeep(2000, 200);
  }
}

// ============== LOG TO SD CARD ==============
void logTradeToSD(String symbol, String type, float price, float pnl) {
  if (!SD.begin(PIN_SD_CS)) return;
  
  File file = SD.open("/trades.csv", FILE_APPEND);
  if (file) {
    file.print(millis());
    file.print(",");
    file.print(symbol);
    file.print(",");
    file.print(type);
    file.print(",");
    file.print(price);
    file.print(",");
    file.println(pnl);
    file.close();
  }
}

// ============== SCREEN RENDERING ==============
void renderScreen() {
  if (!wifiConnected) {
    renderErrorScreen();
    return;
  }
  
  if (numPositions == 0) {
    renderNoPositionsScreen();
    return;
  }
  
  switch (currentScreen) {
    case 0:
      renderOverviewScreen();
      break;
    case 1:
      renderPositionsScreen();
      break;
    case 2:
      renderDetailedPositionScreen(0);  // Show first position
      break;
    case 3:
      renderAlertsScreen();
      break;
  }
}

// ============== SCREEN 0: OVERVIEW ==============
void renderOverviewScreen() {
  tft.fillScreen(TFT_BLACK);
  
  // Header with mode indicator
  uint16_t modeColor = status.paperTrading ? TFT_YELLOW : TFT_RED;
  String modeText = status.paperTrading ? "PAPER MODE" : "LIVE MODE";
  
  tft.fillRect(0, 0, 320, 30, modeColor);
  tft.setTextColor(TFT_BLACK, modeColor);
  tft.setTextDatum(MC_DATUM);
  tft.setTextSize(2);
  tft.drawString(modeText, 160, 15);
  
  // P&L Box
  uint16_t pnlColor = status.todayPnl >= 0 ? TFT_GREEN : TFT_RED;
  tft.fillRoundRect(10, 40, 145, 80, 8, TFT_DARKGREY);
  tft.setTextColor(TFT_WHITE, TFT_DARKGREY);
  tft.setTextSize(1);
  tft.setTextDatum(TC_DATUM);
  tft.drawString("Today's P&L", 82, 50);
  
  tft.setTextColor(pnlColor, TFT_DARKGREY);
  tft.setTextSize(2);
  String pnlStr = (status.todayPnl >= 0 ? "+" : "") + String(status.todayPnl, 0);
  tft.drawString(pnlStr, 82, 75);
  
  // Win Rate Box
  tft.fillRoundRect(165, 40, 145, 80, 8, TFT_DARKGREY);
  tft.setTextColor(TFT_WHITE, TFT_DARKGREY);
  tft.setTextSize(1);
  tft.drawString("Win Rate", 237, 50);
  
  tft.setTextColor(TFT_CYAN, TFT_DARKGREY);
  tft.setTextSize(2);
  tft.drawString(String(status.winRate, 0) + "%", 237, 75);
  
  // Positions & Trades
  tft.fillRoundRect(10, 130, 145, 60, 8, TFT_DARKGREY);
  tft.setTextColor(TFT_WHITE, TFT_DARKGREY);
  tft.setTextSize(1);
  tft.drawString("Open Positions", 82, 140);
  tft.setTextSize(2);
  tft.setTextColor(TFT_ORANGE, TFT_DARKGREY);
  tft.drawString(String(numPositions), 82, 160);
  
  tft.fillRoundRect(165, 130, 145, 60, 8, TFT_DARKGREY);
  tft.setTextColor(TFT_WHITE, TFT_DARKGREY);
  tft.setTextSize(1);
  tft.drawString("Total Trades", 237, 140);
  tft.setTextSize(2);
  tft.setTextColor(TFT_CYAN, TFT_DARKGREY);
  tft.drawString(String(status.totalTrades), 237, 160);
  
  // Capital
  tft.fillRoundRect(10, 200, 300, 40, 8, TFT_DARKGREY);
  tft.setTextColor(TFT_WHITE, TFT_DARKGREY);
  tft.setTextSize(1);
  tft.drawString("Capital: Rs." + String(status.capital, 0), 160, 220);
  
  // Footer
  tft.setTextColor(TFT_GREY, TFT_BLACK);
  tft.setTextSize(1);
  tft.drawString("Screen 1/4 - Auto-cycling", 160, 240);
}

// ============== SCREEN 1: POSITIONS LIST ==============
void renderPositionsScreen() {
  tft.fillScreen(TFT_BLACK);
  
  // Header
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setTextDatum(TC_DATUM);
  tft.setTextSize(2);
  tft.drawString("OPEN POSITIONS", 160, 10);
  tft.drawFastHLine(10, 30, 300, TFT_WHITE);
  
  // List positions
  int y = 45;
  for (int i = 0; i < numPositions && i < 4; i++) {
    renderPositionRow(i, 10, y, 300, 45);
    y += 50;
  }
  
  // Footer
  tft.setTextColor(TFT_GREY, TFT_BLACK);
  tft.setTextSize(1);
  tft.drawString("Screen 2/4", 160, 240);
}

// ============== RENDER SINGLE POSITION ROW ==============
void renderPositionRow(int idx, int x, int y, int w, int h) {
  Position& pos = positions[idx];
  
  // Background
  uint16_t bgColor = pos.pnl >= 0 ? 0x0A20 : 0x2000;  // Dark green or dark red
  tft.fillRoundRect(x, y, w, h, 5, bgColor);
  
  // Symbol
  tft.setTextColor(TFT_WHITE, bgColor);
  tft.setTextDatum(TL_DATUM);
  tft.setTextSize(2);
  tft.drawString(pos.symbol, x + 10, y + 5);
  
  // Quantity
  tft.setTextSize(1);
  tft.setTextColor(TFT_LIGHTGREY, bgColor);
  tft.drawString(String(pos.quantity) + " shares", x + 10, y + 25);
  
  // P&L (right side)
  tft.setTextDatum(TR_DATUM);
  tft.setTextSize(2);
  uint16_t pnlColor = pos.pnl >= 0 ? TFT_GREEN : TFT_RED;
  tft.setTextColor(pnlColor, bgColor);
  String pnlStr = (pos.pnl >= 0 ? "+" : "") + String(pos.pnl, 0);
  tft.drawString(pnlStr, x + w - 10, y + 15);
  
  // Border
  tft.drawRoundRect(x, y, w, h, 5, pos.pnl >= 0 ? TFT_GREEN : TFT_RED);
}

// ============== SCREEN 2: DETAILED POSITION ==============
void renderDetailedPositionScreen(int idx) {
  if (idx >= numPositions) idx = 0;
  Position& pos = positions[idx];
  
  tft.fillScreen(TFT_BLACK);
  
  // Symbol header
  tft.fillRect(0, 0, 320, 50, pos.pnl >= 0 ? TFT_DARKGREEN : TFT_DARKRED);
  tft.setTextColor(TFT_WHITE, pos.pnl >= 0 ? TFT_DARKGREEN : TFT_DARKRED);
  tft.setTextDatum(MC_DATUM);
  tft.setTextSize(3);
  tft.drawString(pos.symbol, 160, 25);
  
  // Large P&L
  tft.setTextDatum(MC_DATUM);
  tft.setTextSize(4);
  uint16_t pnlColor = pos.pnl >= 0 ? TFT_GREEN : TFT_RED;
  tft.setTextColor(pnlColor, TFT_BLACK);
  String pnlStr = (pos.pnl >= 0 ? "+" : "") + String(pos.pnl, 0);
  tft.drawString(pnlStr, 160, 90);
  
  tft.setTextSize(2);
  tft.drawString(String(pos.pnlPercent, 1) + "%", 160, 125);
  
  // Price grid
  tft.setTextDatum(TC_DATUM);
  tft.setTextSize(1);
  
  // Entry
  tft.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
  tft.drawString("Entry", 60, 150);
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setTextSize(2);
  tft.drawString("Rs." + String(pos.entryPrice, 1), 60, 165);
  
  // LTP
  tft.setTextSize(1);
  tft.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
  tft.drawString("LTP", 160, 150);
  tft.setTextColor(TFT_CYAN, TFT_BLACK);
  tft.setTextSize(2);
  tft.drawString("Rs." + String(pos.ltp, 1), 160, 165);
  
  // SL
  tft.setTextSize(1);
  tft.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
  tft.drawString("SL", 260, 150);
  tft.setTextColor(TFT_RED, TFT_BLACK);
  tft.setTextSize(2);
  tft.drawString("Rs." + String(pos.sl, 0), 260, 165);
  
  // Progress bar background
  int pbX = 30, pbY = 195, pbW = 260, pbH = 15;
  tft.fillRect(pbX, pbY, pbW, pbH, TFT_DARKGREY);
  
  // Calculate progress
  float totalRange = pos.tp - pos.sl;
  float progress = totalRange > 0 ? ((pos.ltp - pos.sl) / totalRange) : 0.5;
  int fillW = constrain((int)(pbW * progress), 0, pbW);
  
  // Progress fill with gradient
  uint16_t barColor = pos.pnl >= 0 ? TFT_GREEN : TFT_ORANGE;
  tft.fillRect(pbX, pbY, fillW, pbH, barColor);
  
  // Border
  tft.drawRect(pbX, pbY, pbW, pbH, TFT_WHITE);
  
  // Labels
  tft.setTextSize(1);
  tft.setTextColor(TFT_RED, TFT_BLACK);
  tft.drawString("SL", pbX, pbY + 20);
  tft.setTextColor(TFT_GREEN, TFT_BLACK);
  tft.drawString("TP", pbX + pbW, pbY + 20);
  
  // Footer
  tft.setTextColor(TFT_GREY, TFT_BLACK);
  tft.drawString("Screen 3/4 - " + pos.symbol, 160, 240);
}

// ============== SCREEN 3: ALERTS/HISTORY ==============
void renderAlertsScreen() {
  tft.fillScreen(TFT_BLACK);
  
  // Header
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setTextDatum(TC_DATUM);
  tft.setTextSize(2);
  tft.drawString("TRADE HISTORY", 160, 10);
  tft.drawFastHLine(10, 30, 300, TFT_WHITE);
  
  // Show recent alerts
  int y = 45;
  tft.setTextDatum(TL_DATUM);
  
  for (int i = 0; i < min(alertCount, 6); i++) {
    int idx = (alertIndex - 1 - i + 20) % 20;
    TradeAlert& alert = alerts[idx];
    
    // Type icon
    uint16_t color = TFT_WHITE;
    if (alert.type == "BUY") color = TFT_GREEN;
    else if (alert.type == "SELL") color = TFT_RED;
    else if (alert.type == "TP_HIT") color = TFT_CYAN;
    
    tft.setTextColor(color, TFT_BLACK);
    tft.setTextSize(1);
    tft.drawString(alert.type, 10, y);
    
    // Symbol
    tft.setTextColor(TFT_WHITE, TFT_BLACK);
    tft.drawString(alert.symbol, 60, y);
    
    // PnL if available
    if (alert.pnl != 0) {
      tft.setTextDatum(TR_DATUM);
      uint16_t pnlColor = alert.pnl >= 0 ? TFT_GREEN : TFT_RED;
      tft.setTextColor(pnlColor, TFT_BLACK);
      String pnlStr = (alert.pnl >= 0 ? "+" : "") + String(alert.pnl, 0);
      tft.drawString(pnlStr, 310, y);
      tft.setTextDatum(TL_DATUM);
    }
    
    y += 30;
  }
  
  if (alertCount == 0) {
    tft.setTextColor(TFT_GREY, TFT_BLACK);
    tft.setTextDatum(MC_DATUM);
    tft.drawString("No recent trades", 160, 120);
  }
  
  // Footer
  tft.setTextColor(TFT_GREY, TFT_BLACK);
  tft.setTextDatum(TC_DATUM);
  tft.drawString("Screen 4/4", 160, 240);
}

// ============== ERROR SCREEN ==============
void renderErrorScreen() {
  tft.fillScreen(TFT_BLACK);
  
  tft.setTextColor(TFT_RED, TFT_BLACK);
  tft.setTextDatum(MC_DATUM);
  tft.setTextSize(2);
  tft.drawString("CONNECTION ERROR", 160, 100);
  
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setTextSize(1);
  tft.drawString(errorMessage, 160, 130);
  
  tft.drawString("Retrying...", 160, 160);
  
  // Blinking LED
  digitalWrite(PIN_LED_R, (millis() / 500) % 2);
}

// ============== NO POSITIONS SCREEN ==============
void renderNoPositionsScreen() {
  tft.fillScreen(TFT_BLACK);
  
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.setTextDatum(MC_DATUM);
  tft.setTextSize(2);
  tft.drawString("NO OPEN POSITIONS", 160, 80);
  
  tft.setTextColor(TFT_GREY, TFT_BLACK);
  tft.setTextSize(1);
  tft.drawString("Waiting for trades...", 160, 110);
  
  // Today's P&L
  uint16_t pnlColor = status.todayPnl >= 0 ? TFT_GREEN : TFT_RED;
  tft.setTextColor(pnlColor, TFT_BLACK);
  tft.setTextSize(3);
  String pnlStr = (status.todayPnl >= 0 ? "+" : "") + String(status.todayPnl, 0);
  tft.drawString(pnlStr, 160, 160);
}

// ============== BUTTON HANDLING ==============
void handleButtons() {
  // Button 1: Cycle screens manually
  if (digitalRead(PIN_BTN_1) == LOW) {
    delay(50);  // Debounce
    if (digitalRead(PIN_BTN_1) == LOW) {
      currentScreen = (currentScreen + 1) % NUM_SCREENS;
      lastDisplayCycle = millis();  // Reset auto-cycle timer
      playBeep(1000, 50);
      while (digitalRead(PIN_BTN_1) == LOW);  // Wait for release
    }
  }
  
  // Button 2: Toggle backlight / Alert
  if (digitalRead(PIN_BTN_2) == LOW) {
    delay(50);
    if (digitalRead(PIN_BTN_2) == LOW) {
      // Could trigger manual refresh or alert
      playBeep(1500, 100);
      while (digitalRead(PIN_BTN_2) == LOW);
    }
  }
}

// ============== LED CONTROL ==============
void updateLEDs() {
  // Green = OK, Paper mode or profit
  // Red = Live mode and/or loss
  // Blue = Connecting
  
  if (!wifiConnected) {
    analogWrite(PIN_LED_B, 255);
    analogWrite(PIN_LED_R, 0);
    analogWrite(PIN_LED_G, 0);
  } else if (!status.paperTrading) {
    // Live mode - always red warning
    analogWrite(PIN_LED_R, 255);
    analogWrite(PIN_LED_G, 0);
    analogWrite(PIN_LED_B, 0);
  } else if (status.todayPnl < -1000) {
    // Big loss - pulsing red
    int brightness = (millis() % 1000) / 4;
    analogWrite(PIN_LED_R, brightness);
    analogWrite(PIN_LED_G, 0);
    analogWrite(PIN_LED_B, 0);
  } else if (status.todayPnl > 1000) {
    // Good profit - green
    analogWrite(PIN_LED_R, 0);
    analogWrite(PIN_LED_G, 255);
    analogWrite(PIN_LED_B, 0);
  } else {
    // Normal - dim green
    analogWrite(PIN_LED_R, 0);
    analogWrite(PIN_LED_G, 50);
    analogWrite(PIN_LED_B, 0);
  }
}

// ============== SOUND FUNCTIONS ==============
void playBeep(int frequency, int duration) {
  tone(PIN_BUZZER, frequency, duration);
}

// Custom color definitions
#define TFT_PRIMARY 0x04FF  // Bright green-blue
#define TFT_DARKGREEN 0x0320
#define TFT_DARKRED 0x3000
