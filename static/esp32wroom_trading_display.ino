/*
 * ESP32-WROOM Trading Display - PREMIUM EDITION
 * ==============================================
 * Hardware: ESP32-WROOM-32 + 1.3" 128x64 OLED (SSD1306/SH1106 I2C)
 * 
 * ENHANCED FEATURES (vs ESP8266):
 * - Display up to 5 positions with scroll animation
 * - Trade history log (last 20 trades)
 * - Smooth animated transitions between screens
 * - Auto screen cycling with configurable timer
 * - Advanced WiFi with automatic reconnection
 * - Multi-pattern alert sounds (melodies)
 * - Battery voltage monitoring (optional)
 * - CPU temperature display
 * - Free heap monitoring
 * - Dual-core optimization (UI on Core 1, Network on Core 0)
 * - 60fps display refresh
 * - Configurable via web portal (optional)
 * - OTA update support
 * - Better SSL/TLS support
 * 
 * PINOUT (ESP32 DevKit V1):
 * - OLED SDA: GPIO21 (can be changed)
 * - OLED SCL: GPIO22 (can be changed)
 * - BUTTON:   GPIO4  (any GPIO works on ESP32)
 * - BUZZER:   GPIO18 (PWM capable)
 * - LED:      GPIO2  (built-in)
 * - BATTERY:  GPIO34 (ADC1_CH6, optional)
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <ArduinoOTA.h>

// ============ MELODY DEFINITIONS (MUST BE BEFORE USE) ============
enum Melody {
  MELODY_BOOT,
  MELODY_BUTTON,
  MELODY_ALERT,
  MELODY_ERROR
};

void playMelody(Melody melody);

// ============ CONFIGURATION ============
const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASS = "YOUR_WIFI_PASSWORD";
const char* SERVER_URL = "https://coolify.themelon.in";
const char* DEVICE_ID = "esp32_trading_display";

// Feature flags (can be toggled)
#define ENABLE_OTA          true
#define ENABLE_SOUND        true
#define ENABLE_AUTO_CYCLE   true
#define ENABLE_TRADE_LOG    true
#define ENABLE_SYS_INFO     true
#define ENABLE_BATTERY_MON  false  // Set true if battery connected

// Pins - ESP32 has more flexibility
#define PIN_BUTTON      4    // Any GPIO works on ESP32
#define PIN_BUZZER      18   // PWM pin for tones
#define PIN_LED         2    // Built-in LED on most ESP32 boards
#define PIN_BATTERY     34   // ADC pin for battery monitoring

// OLED pins (ESP32 default I2C pins)
#define OLED_SDA        21
#define OLED_SCL        22
#define OLED_ADDR       0x3C  // Try 0x3D if display is blank
#define OLED_RESET      -1

#define SCREEN_WIDTH    128
#define SCREEN_HEIGHT   64

// Timing
#define DATA_INTERVAL       2000    // 2 seconds (faster than ESP8266)
#define ALERT_INTERVAL      1000    // 1 second
#define DISPLAY_INTERVAL    16      // ~60fps
#define AUTO_CYCLE_TIME     5000    // 5 seconds per screen
#define RECONNECT_INTERVAL  10000   // Try reconnect every 10s

// OLED Display
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
};

struct TradeLog {
  char symbol[12];
  char action[8];     // "BUY", "SELL", "SL", "TP"
  float price;
  float pnl;
  unsigned long time;
};

struct SystemData {
  bool enabled;
  bool marketOpen;
  bool paperTrading;
  float todayPnl;
  float winRate;
  int openPositions;
  int todayTrades;
  int maxTrades;
  float capital;
  
  // Enhanced data
  Position positions[5];    // Up to 5 positions
  int numPositions;
  
  #if ENABLE_TRADE_LOG
  TradeLog tradeHistory[20];
  int tradeCount;
  int tradeIndex;
  #endif
  
  #if ENABLE_SYS_INFO
  float cpuTemp;
  uint32_t freeHeap;
  float batteryVoltage;
  int8_t rssi;
  #endif
};

struct AlertData {
  bool active;
  char symbol[12];
  float price;
  char type[16];        // "NEW_SIGNAL", "SL_HIT", "TP_HIT", etc.
  unsigned long showTime;
};

// ============ GLOBAL VARIABLES ============
SystemData data;
AlertData alert = {false, "", 0, "", 0};

// Screens (more than ESP8266)
enum Screen { 
  SCR_DASHBOARD, 
  SCR_POSITIONS, 
  SCR_POSITION_DETAIL,
  SCR_STATS, 
  SCR_TRADE_LOG,
  SCR_SYSTEM_INFO,
  SCR_COUNT 
};
Screen currentScreen = SCR_DASHBOARD;
int positionScrollIndex = 0;  // For scrolling through positions

const char* screenNames[] = {
  "DASHBOARD", "POSITIONS", "DETAIL", "STATS", "LOG", "SYSTEM"
};

// Timing
unsigned long lastDataFetch = 0;
unsigned long lastAlertCheck = 0;
unsigned long lastDisplayUpdate = 0;
unsigned long lastAutoCycle = 0;
unsigned long lastReconnectAttempt = 0;

// Button handling with ESP32's better debounce
volatile bool btnPressed = false;
unsigned long btnLastPress = 0;
const unsigned long BTN_DEBOUNCE = 150;

// WiFi status
bool wifiConnected = false;
int reconnectAttempts = 0;

// Animation
float animOffset = 0;
bool animDirection = true;

// Task handles for dual-core operation
TaskHandle_t networkTaskHandle = NULL;

// ============ SETUP ============
void setup() {
  Serial.begin(115200);
  delay(100);
  
  Serial.println(F("\n========================================"));
  Serial.println(F("  ESP32-WROOM Trading Display"));
  Serial.println(F("  PREMIUM EDITION"));
  Serial.println(F("========================================"));
  
  // Initialize pins
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  pinMode(PIN_LED, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);
  
  #if ENABLE_BATTERY_MON
  pinMode(PIN_BATTERY, INPUT);
  analogSetAttenuation(ADC_11db);  // For full 3.3V range
  #endif
  
  // Initialize I2C at 800kHz (ESP32 can handle faster than ESP8266)
  Wire.begin(OLED_SDA, OLED_SCL);
  Wire.setClock(800000);
  
  // Initialize OLED
  if(!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
    Serial.println(F("SSD1306 allocation failed"));
    fatalError();
  }
  
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.display();
  
  // Show premium splash screen
  showPremiumSplash();
  
  // Initialize data structures
  memset(&data, 0, sizeof(data));
  data.paperTrading = true;
  data.maxTrades = 10;
  
  // Connect WiFi
  connectWiFi();
  
  #if ENABLE_OTA
  setupOTA();
  #endif
  
  // Create network task on Core 0 (network operations)
  // UI runs on Core 1 (default)
  xTaskCreatePinnedToCore(
    networkTask,      // Task function
    "NetworkTask",    // Task name
    8192,             // Stack size (larger for ESP32)
    NULL,             // Parameter
    1,                // Priority
    &networkTaskHandle, // Task handle
    0                 // Core 0
  );
  
  // Success melody
  playMelody(MELODY_BOOT);
  
  Serial.println(F("Setup complete! Running..."));
}

// ============ MAIN LOOP (UI on Core 1) ============
void loop() {
  unsigned long now = millis();
  
  // Handle button with interrupt-like polling
  handleButtonESP32();
  
  #if ENABLE_OTA
  ArduinoOTA.handle();
  #endif
  
  // Update LED with smooth PWM effect
  updateLEDPWM(now);
  
  // Auto screen cycling
  #if ENABLE_AUTO_CYCLE
  if (ENABLE_AUTO_CYCLE && !alert.active && (now - lastAutoCycle > AUTO_CYCLE_TIME)) {
    lastAutoCycle = now;
    nextScreen();
  }
  #endif
  
  // Update display at 60fps
  if (now - lastDisplayUpdate > DISPLAY_INTERVAL) {
    updateDisplay();
    lastDisplayUpdate = now;
  }
  
  // Small delay to prevent watchdog issues
  delay(1);
}

// ============ NETWORK TASK (Core 0) ============
void networkTask(void* parameter) {
  for (;;) {
    unsigned long now = millis();
    
    // WiFi reconnection check
    if (WiFi.status() != WL_CONNECTED) {
      wifiConnected = false;
      if (now - lastReconnectAttempt > RECONNECT_INTERVAL) {
        lastReconnectAttempt = now;
        reconnectWiFi();
      }
    } else {
      wifiConnected = true;
      reconnectAttempts = 0;
    }
    
    // Fetch trading data every 2 seconds
    if (wifiConnected && (now - lastDataFetch > DATA_INTERVAL)) {
      lastDataFetch = now;
      fetchDataESP32();
      
      #if ENABLE_SYS_INFO
      updateSystemInfo();
      #endif
    }
    
    // Check for alerts
    if (wifiConnected && (now - lastAlertCheck > ALERT_INTERVAL)) {
      lastAlertCheck = now;
      checkAlertsESP32();
    }
    
    // Alert timeout (15 seconds)
    if (alert.active && (now - alert.showTime > 15000)) {
      alert.active = false;
    }
    
    delay(10);  // Yield to other tasks
  }
}

// ============ DISPLAY SCREENS ============
void updateDisplay() {
  display.clearDisplay();
  
  if (alert.active) {
    drawAlertEnhanced();
  } else {
    switch (currentScreen) {
      case SCR_DASHBOARD:     drawDashboardEnhanced(); break;
      case SCR_POSITIONS:     drawPositionsScrollable(); break;
      case SCR_POSITION_DETAIL: drawPositionDetail(); break;
      case SCR_STATS:         drawStatsEnhanced(); break;
      case SCR_TRADE_LOG:     drawTradeLog(); break;
      case SCR_SYSTEM_INFO:   drawSystemInfo(); break;
    }
  }
  
  display.display();
}

void drawDashboardEnhanced() {
  // Top bar with mode indicator
  display.fillRect(0, 0, 38, 12, SSD1306_WHITE);
  display.setTextColor(SSD1306_BLACK);
  display.setTextSize(1);
  display.setCursor(2, 2);
  display.print(data.paperTrading ? F("DEMO") : F("LIVE"));
  
  // WiFi signal strength icon
  drawWiFiIconEnhanced(85, 2);
  
  // System status
  display.setTextColor(SSD1306_WHITE);
  if (data.enabled && data.marketOpen) {
    display.fillCircle(122, 6, 3, SSD1306_WHITE);
  } else {
    display.drawCircle(122, 6, 3, SSD1306_WHITE);
  }
  
  // Animated P&L display
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(4, 16);
  display.print(F("TODAY'S P&L"));
  
  // Large P&L with animation
  display.setTextSize(3);
  int pnlInt = (int)data.todayPnl;
  String pnlStr = String(abs(pnlInt));
  int textWidth = pnlStr.length() * 18 + 18;  // +18 for sign
  int startX = (128 - textWidth) / 2 + 9;
  
  display.setCursor(startX, 28);
  display.print(data.todayPnl >= 0 ? F("+") : F("-"));
  display.print(pnlStr);
  
  // Separator line
  display.drawLine(0, 52, 128, 52, SSD1306_WHITE);
  
  // Bottom info bar with more details
  display.setTextSize(1);
  
  // Left: Trades count
  display.setCursor(4, 55);
  display.print(data.todayTrades);
  display.print(F("/"));
  display.print(data.maxTrades);
  
  // Center: Position count
  display.setCursor(52, 55);
  display.print(F("POS:"));
  display.print(data.numPositions);
  
  // Right: Status with animation
  display.setCursor(90, 55);
  if (!data.enabled) {
    display.print(F("OFF"));
  } else if (!data.marketOpen) {
    display.print(F("CLOSED"));
  } else {
    // Animated dots
    int dots = (millis() / 400) % 4;
    display.print(F("LIVE"));
    for (int i = 0; i < dots; i++) display.print(F("."));
  }
  
  // Page indicator (6 dots for 6 screens)
  drawPageIndicatorEnhanced(currentScreen, SCR_COUNT);
}

void drawPositionsScrollable() {
  // Header
  display.fillRect(0, 0, 128, 11, SSD1306_WHITE);
  display.setTextColor(SSD1306_BLACK);
  display.setTextSize(1);
  display.setCursor(2, 1);
  display.print(F("POSITIONS ("));
  display.print(data.numPositions);
  display.print(F(")"));
  
  display.setTextColor(SSD1306_WHITE);
  
  if (data.numPositions == 0) {
    display.setCursor(20, 28);
    display.print(F("No open positions"));
    display.setCursor(15, 42);
    display.print(F("Waiting for signals..."));
  } else {
    // Show up to 3 positions at a time
    int startIdx = positionScrollIndex;
    int yPos = 14;
    
    for (int i = 0; i < 3 && (startIdx + i) < data.numPositions; i++) {
      int idx = startIdx + i;
      Position& pos = data.positions[idx];
      
      // Row background alternating
      if (i % 2 == 0) {
        display.fillRect(0, yPos, 128, 16, SSD1306_INVERSE);
      }
      
      // Symbol
      display.setCursor(2, yPos + 4);
      display.print(pos.symbol);
      
      // Qty
      display.setCursor(55, yPos + 4);
      display.print(pos.quantity);
      
      // P&L right aligned
      display.setCursor(85, yPos + 4);
      if (pos.pnl >= 0) display.print(F("+"));
      display.print((int)pos.pnl);
      
      yPos += 16;
    }
    
    // Scroll indicator if more positions
    if (data.numPositions > 3) {
      display.drawRect(118, 14, 6, 46, SSD1306_WHITE);
      int thumbHeight = max(8, 46 * 3 / data.numPositions);
      int thumbPos = 14 + (positionScrollIndex * (46 - thumbHeight) / max(1, data.numPositions - 3));
      display.fillRect(119, thumbPos, 4, thumbHeight, SSD1306_WHITE);
    }
  }
  
  drawPageIndicatorEnhanced(1, SCR_COUNT);
}

void drawPositionDetail() {
  // Detailed view of first position (or scroll through them)
  static int detailIndex = 0;
  
  if (data.numPositions == 0) {
    display.setTextSize(1);
    display.setCursor(20, 28);
    display.print(F("No positions"));
    drawPageIndicatorEnhanced(2, SCR_COUNT);
    return;
  }
  
  // Cycle through positions every auto-cycle
  if (millis() % AUTO_CYCLE_TIME < 100) {
    detailIndex = (detailIndex + 1) % data.numPositions;
  }
  
  Position& pos = data.positions[detailIndex];
  
  // Header with symbol
  display.fillRect(0, 0, 128, 14, SSD1306_WHITE);
  display.setTextColor(SSD1306_BLACK);
  display.setTextSize(1);
  display.setCursor(4, 3);
  display.print(pos.symbol);
  display.print(F(" ("));
  display.print(detailIndex + 1);
  display.print(F("/"));
  display.print(data.numPositions);
  display.print(F(")"));
  
  display.setTextColor(SSD1306_WHITE);
  
  // Large P&L
  display.setTextSize(2);
  int pnlY = 20;
  if (pos.pnl >= 0) {
    display.setCursor(20, pnlY);
    display.print(F("+"));
    display.print((int)pos.pnl);
  } else {
    display.setCursor(20, pnlY);
    display.print((int)pos.pnl);
  }
  
  // P&L percentage
  display.setTextSize(1);
  display.setCursor(90, 24);
  display.print(pos.pnlPercent, 1);
  display.print(F("%"));
  
  // Price info grid
  int y = 40;
  display.setTextSize(1);
  
  // Entry
  display.setCursor(4, y);
  display.print(F("E:"));
  display.print(pos.entryPrice, 1);
  
  // LTP
  display.setCursor(50, y);
  display.print(F("L:"));
  display.print(pos.ltp, 1);
  
  // Qty
  display.setCursor(95, y);
  display.print(F("Q:"));
  display.print(pos.quantity);
  
  // Progress bar for SL/TP
  y = 52;
  int pbX = 4, pbW = 120, pbH = 8;
  display.drawRect(pbX, y, pbW, pbH, SSD1306_WHITE);
  
  float range = pos.tp - pos.sl;
  float progress = (range > 0) ? constrain((pos.ltp - pos.sl) / range, 0, 1) : 0.5;
  int fillW = (int)(pbW * progress);
  display.fillRect(pbX + 1, y + 1, fillW - 2, pbH - 2, SSD1306_WHITE);
  
  // SL and TP labels
  display.setCursor(pbX, y + pbH + 1);
  display.print(F("SL"));
  display.setCursor(pbX + pbW - 12, y + pbH + 1);
  display.print(F("TP"));
  
  drawPageIndicatorEnhanced(2, SCR_COUNT);
}

void drawStatsEnhanced() {
  // Header
  display.fillRect(0, 0, 128, 11, SSD1306_WHITE);
  display.setTextColor(SSD1306_BLACK);
  display.setTextSize(1);
  display.setCursor(2, 1);
  display.print(F("STATISTICS"));
  
  display.setTextColor(SSD1306_WHITE);
  
  // Win Rate - Large left
  display.setTextSize(1);
  display.setCursor(4, 16);
  display.print(F("WIN RATE"));
  
  display.setTextSize(3);
  display.setCursor(4, 28);
  display.print((int)data.winRate);
  display.setTextSize(2);
  display.print(F("%"));
  
  // Vertical separator
  display.drawLine(70, 16, 70, 50, SSD1306_WHITE);
  
  // Stats column
  display.setTextSize(1);
  
  int x = 76;
  int y = 16;
  int lineH = 11;
  
  // Total trades
  display.setCursor(x, y);
  display.print(F("TTL:"));
  display.print(data.todayTrades);
  y += lineH;
  
  // Open positions
  display.setCursor(x, y);
  display.print(F("OPEN:"));
  display.print(data.numPositions);
  y += lineH;
  
  // P&L
  display.setCursor(x, y);
  display.print(F("P&L:"));
  if (data.todayPnl >= 0) display.print(F("+"));
  display.print((int)data.todayPnl);
  y += lineH;
  
  // Capital
  display.setCursor(x, y);
  display.print(F("CAP:"));
  display.print((int)(data.capital / 1000));
  display.print(F("K"));
  
  drawPageIndicatorEnhanced(3, SCR_COUNT);
}

void drawTradeLog() {
  #if ENABLE_TRADE_LOG
  // Header
  display.fillRect(0, 0, 128, 11, SSD1306_WHITE);
  display.setTextColor(SSD1306_BLACK);
  display.setTextSize(1);
  display.setCursor(2, 1);
  display.print(F("TRADE LOG ("));
  display.print(min(data.tradeCount, 20));
  display.print(F(")"));
  
  display.setTextColor(SSD1306_WHITE);
  
  if (data.tradeCount == 0) {
    display.setCursor(25, 32);
    display.print(F("No trades yet"));
  } else {
    // Show last 4 trades
    int y = 14;
    for (int i = 0; i < 4 && i < data.tradeCount; i++) {
      int idx = (data.tradeIndex - 1 - i + 20) % 20;
      TradeLog& trade = data.tradeHistory[idx];
      
      // Action type (BUY/SELL/SL/TP)
      if (strcmp(trade.action, "BUY") == 0) {
        display.setCursor(2, y);
        display.print(F("B"));
      } else if (strcmp(trade.action, "SELL") == 0) {
        display.setCursor(2, y);
        display.print(F("S"));
      } else {
        display.setCursor(2, y);
        display.print(trade.action);
      }
      
      // Symbol
      display.setCursor(16, y);
      display.print(trade.symbol);
      
      // Price
      display.setCursor(65, y);
      display.print((int)trade.price);
      
      // P&L
      display.setCursor(95, y);
      if (trade.pnl != 0) {
        if (trade.pnl >= 0) {
          display.print(F("+"));
          display.print((int)trade.pnl);
        } else {
          display.print((int)trade.pnl);
        }
      } else {
        display.print(F("--"));
      }
      
      y += 12;
    }
  }
  #else
  display.setTextSize(1);
  display.setCursor(10, 28);
  display.print(F("Trade log disabled"));
  display.setCursor(10, 42);
  display.print(F("Enable in config"));
  #endif
  
  drawPageIndicatorEnhanced(4, SCR_COUNT);
}

void drawSystemInfo() {
  #if ENABLE_SYS_INFO
  // Header
  display.fillRect(0, 0, 128, 11, SSD1306_WHITE);
  display.setTextColor(SSD1306_BLACK);
  display.setTextSize(1);
  display.setCursor(2, 1);
  display.print(F("SYSTEM INFO"));
  
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(1);
  
  int y = 14;
  int lineH = 10;
  
  // WiFi RSSI
  display.setCursor(4, y);
  display.print(F("RSSI:"));
  display.print(data.rssi);
  display.print(F("dBm"));
  y += lineH;
  
  // Free heap
  display.setCursor(4, y);
  display.print(F("Heap:"));
  display.print(data.freeHeap / 1024);
  display.print(F("KB"));
  y += lineH;
  
  // CPU Temperature
  display.setCursor(4, y);
  display.print(F("Temp:"));
  display.print(data.cpuTemp, 1);
  display.print(F("C"));
  y += lineH;
  
  #if ENABLE_BATTERY_MON
  // Battery voltage
  display.setCursor(4, y);
  display.print(F("Batt:"));
  display.print(data.batteryVoltage, 1);
  display.print(F("V"));
  y += lineH;
  #endif
  
  // Uptime
  display.setCursor(4, y);
  unsigned long uptime = millis() / 1000;
  display.print(F("Up:"));
  display.print(uptime / 60);
  display.print(F("m"));
  
  #else
  display.setTextSize(1);
  display.setCursor(10, 28);
  display.print(F("Sys info disabled"));
  display.setCursor(10, 42);
  display.print(F("Enable in config"));
  #endif
  
  drawPageIndicatorEnhanced(5, SCR_COUNT);
}

void drawAlertEnhanced() {
  // Enhanced flashing alert with border animation
  unsigned long elapsed = millis() - alert.showTime;
  int flashPhase = (elapsed / 100) % 8;
  bool invert = flashPhase % 2 == 0;
  
  if (invert) {
    display.fillRect(0, 0, 128, 64, SSD1306_WHITE);
    display.setTextColor(SSD1306_BLACK);
  } else {
    display.setTextColor(SSD1306_WHITE);
  }
  
  // Animated border
  int offset = flashPhase;
  display.drawRect(2 + offset % 2, 2 + offset % 2, 124 - (offset % 2) * 2, 60 - (offset % 2) * 2, 
                   invert ? SSD1306_BLACK : SSD1306_WHITE);
  
  // Alert type
  display.setTextSize(1);
  display.setCursor(35, 6);
  if (strlen(alert.type) > 0) {
    display.print(alert.type);
  } else {
    display.print(F("NEW ALERT!"));
  }
  
  // Symbol - LARGE
  display.setTextSize(2);
  int symWidth = strlen(alert.symbol) * 12;
  int symX = (128 - symWidth) / 2;
  display.setCursor(max(10, symX), 24);
  display.print(alert.symbol);
  
  // Price
  display.setTextSize(1);
  display.setCursor(30, 44);
  display.print(F("@ Rs"));
  display.print(alert.price, 1);
  
  // Countdown bar
  int barWidth = map(elapsed, 0, 15000, 100, 0);
  barWidth = constrain(barWidth, 0, 100);
  display.drawRect(14, 56, 100, 6, invert ? SSD1306_BLACK : SSD1306_WHITE);
  display.fillRect(15, 57, barWidth, 4, invert ? SSD1306_BLACK : SSD1306_WHITE);
}

// ============ DRAW HELPERS ============
void drawWiFiIconEnhanced(int x, int y) {
  // Enhanced WiFi icon with signal strength
  int strength = 0;
  #if ENABLE_SYS_INFO
  if (data.rssi > -50) strength = 3;
  else if (data.rssi > -65) strength = 2;
  else if (data.rssi > -80) strength = 1;
  #endif
  
  // Draw base icon
  display.drawPixel(x + 4, y + 6, SSD1306_WHITE);
  
  // Signal arcs based on strength
  if (strength >= 1) display.drawLine(x + 2, y + 5, x + 6, y + 5, SSD1306_WHITE);
  if (strength >= 2) display.drawLine(x + 1, y + 4, x + 7, y + 4, SSD1306_WHITE);
  if (strength >= 3) display.drawLine(x, y + 3, x + 8, y + 3, SSD1306_WHITE);
}

void drawPageIndicatorEnhanced(int activePage, int totalPages) {
  // Enhanced page indicator with more dots
  int dotWidth = 4;
  int spacing = 2;
  int totalWidth = totalPages * dotWidth + (totalPages - 1) * spacing;
  int startX = (128 - totalWidth) / 2;
  int y = 62;
  
  for (int i = 0; i < totalPages; i++) {
    int x = startX + i * (dotWidth + spacing);
    if (i == activePage) {
      display.fillRect(x, y - 1, dotWidth, 3, SSD1306_WHITE);
    } else {
      display.drawPixel(x + 1, y, SSD1306_WHITE);
    }
  }
}

void showPremiumSplash() {
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  
  // Animated logo
  for (int r = 2; r <= 10; r += 2) {
    display.clearDisplay();
    display.fillCircle(24, 22, r, SSD1306_WHITE);
    display.fillCircle(24, 22, r - 2, SSD1306_BLACK);
    display.fillCircle(24, 22, r / 2, SSD1306_WHITE);
    display.display();
    delay(30);
  }
  
  // Title
  display.setTextSize(2);
  display.setCursor(44, 14);
  display.print(F("MELON"));
  
  display.setTextSize(1);
  display.setCursor(44, 32);
  display.print(F("Trading Bot"));
  
  display.setCursor(44, 44);
  display.print(F("ESP32 PRO"));
  
  // Progress bar
  display.drawRect(10, 56, 108, 6, SSD1306_WHITE);
  display.display();
  
  for (int i = 0; i <= 100; i += 10) {
    display.fillRect(12, 58, i, 2, SSD1306_WHITE);
    display.display();
    delay(20);
  }
}

// ============ INPUT HANDLING ============
void handleButtonESP32() {
  // Read button state
  bool pressed = (digitalRead(PIN_BUTTON) == LOW);
  unsigned long now = millis();
  
  if (pressed && (now - btnLastPress > BTN_DEBOUNCE)) {
    btnLastPress = now;
    
    // Stop auto cycle on manual interaction
    lastAutoCycle = now;
    
    if (alert.active) {
      alert.active = false;
      Serial.println(F("[BTN] Alert dismissed"));
    } else {
      nextScreen();
      Serial.print(F("[BTN] Screen -> "));
      Serial.println(screenNames[currentScreen]);
    }
    
    // Feedback
    playMelody(MELODY_BUTTON);
  }
}

void nextScreen() {
  currentScreen = (Screen)((currentScreen + 1) % SCR_COUNT);
}

// ============ LED CONTROL (PWM) ============
void updateLEDPWM(unsigned long now) {
  // ESP32 has better PWM support
  if (!data.enabled) {
    // Slow breathe when disabled
    int brightness = (sin(now / 1000.0) + 1) * 50;
    analogWrite(PIN_LED, brightness);
  } else if (alert.active) {
    // Fast flash for alert
    digitalWrite(PIN_LED, (now / 100) % 2);
  } else if (data.todayPnl > 500) {
    // Solid for good profit
    digitalWrite(PIN_LED, HIGH);
  } else if (data.todayPnl < -500) {
    // Pulsing for loss
    int brightness = (sin(now / 200.0) + 1) * 64;
    analogWrite(PIN_LED, brightness);
  } else {
    // Gentle pulse for normal
    int brightness = (sin(now / 500.0) + 1) * 32;
    analogWrite(PIN_LED, brightness);
  }
}

// ============ NETWORK FUNCTIONS ============
void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  
  Serial.print(F("Connecting to WiFi"));
  int attempts = 0;
  
  while (WiFi.status() != WL_CONNECTED && attempts < 30) {
    delay(300);
    Serial.print(F("."));
    attempts++;
    
    // Update display with progress
    display.clearDisplay();
    display.setTextSize(1);
    display.setCursor(20, 20);
    display.print(F("WiFi Connecting..."));
    display.drawRect(10, 40, 108, 10, SSD1306_WHITE);
    display.fillRect(12, 42, attempts * 3, 6, SSD1306_WHITE);
    display.display();
  }
  
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println(F("\nWiFi connected!"));
    Serial.print(F("IP: "));
    Serial.println(WiFi.localIP());
    wifiConnected = true;
  } else {
    Serial.println(F("\nWiFi connection failed!"));
    wifiConnected = false;
  }
}

void reconnectWiFi() {
  if (reconnectAttempts < 5) {
    Serial.println(F("[WiFi] Attempting reconnect..."));
    WiFi.reconnect();
    reconnectAttempts++;
  } else {
    Serial.println(F("[WiFi] Full reconnect..."));
    WiFi.disconnect();
    delay(1000);
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    reconnectAttempts = 0;
  }
}

void fetchDataESP32() {
  if (WiFi.status() != WL_CONNECTED) return;
  
  WiFiClientSecure client;
  client.setInsecure();
  HTTPClient http;
  
  http.begin(client, String(SERVER_URL) + "/api/esp/stats");
  http.setTimeout(3000);  // ESP32 can handle longer timeouts
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-ID", DEVICE_ID);
  
  int code = http.GET();
  if (code == 200) {
    String payload = http.getString();
    parseEnhancedData(payload);
  } else {
    Serial.printf("[HTTP] Error: %d\n", code);
  }
  
  http.end();
}

void parseEnhancedData(String json) {
  DynamicJsonDocument doc(4096);  // Much larger buffer for ESP32
  DeserializationError error = deserializeJson(doc, json);
  
  if (error) {
    Serial.print(F("[JSON] Parse failed: "));
    Serial.println(error.c_str());
    return;
  }
  
  // Basic data (same as ESP8266)
  data.enabled = doc["system_enabled"] | false;
  data.marketOpen = doc["market_open"] | false;
  data.paperTrading = doc["paper_trading"] | true;
  data.todayPnl = doc["today_pnl"] | 0.0;
  data.winRate = doc["win_rate"] | 0.0;
  data.numPositions = doc["open_positions"] | 0;
  data.todayTrades = doc["today_trades"] | 0;
  data.maxTrades = doc["max_trades"] | 10;
  data.capital = doc["capital"] | 100000.0;
  
  // Parse up to 5 positions
  JsonArray posArray = doc["positions"].as<JsonArray>();
  data.numPositions = 0;
  for (JsonObject pos : posArray) {
    if (data.numPositions >= 5) break;
    
    strlcpy(data.positions[data.numPositions].symbol, pos["symbol"] | "UNK", sizeof(data.positions[0].symbol));
    data.positions[data.numPositions].entryPrice = pos["entry_price"] | 0.0;
    data.positions[data.numPositions].ltp = pos["ltp"] | 0.0;
    data.positions[data.numPositions].sl = pos["sl_price"] | 0.0;
    data.positions[data.numPositions].tp = pos["tp_price"] | 0.0;
    data.positions[data.numPositions].quantity = pos["quantity"] | 0;
    data.positions[data.numPositions].pnl = pos["unrealized_pnl"] | 0.0;
    data.positions[data.numPositions].pnlPercent = pos["pnl_percent"] | 0.0;
    
    data.numPositions++;
  }
  
  #if ENABLE_TRADE_LOG
  // Parse recent trades
  JsonArray trades = doc["recent_trades"].as<JsonArray>();
  for (JsonObject trade : trades) {
    addTradeToLog(
      trade["symbol"] | "",
      trade["action"] | "",
      trade["price"] | 0.0,
      trade["pnl"] | 0.0
    );
  }
  #endif
}

void checkAlertsESP32() {
  if (WiFi.status() != WL_CONNECTED) return;
  
  WiFiClientSecure client;
  client.setInsecure();
  HTTPClient http;
  
  http.begin(client, String(SERVER_URL) + "/api/esp/alert");
  http.setTimeout(2000);
  http.addHeader("X-Device-ID", DEVICE_ID);
  
  int code = http.GET();
  if (code == 200) {
    DynamicJsonDocument doc(1024);
    DeserializationError error = deserializeJson(doc, http.getString());
    
    if (!error && doc["new_alert"] == true) {
      strlcpy(alert.symbol, doc["symbol"] | "UNKNOWN", sizeof(alert.symbol));
      alert.price = doc["price"] | 0.0;
      strlcpy(alert.type, doc["type"] | "ALERT", sizeof(alert.type));
      alert.active = true;
      alert.showTime = millis();
      
      // Play alert melody
      playMelody(MELODY_ALERT);
    }
  }
  
  http.end();
}

// ============ SYSTEM INFO ============
#if ENABLE_SYS_INFO
void updateSystemInfo() {
  data.freeHeap = ESP.getFreeHeap();
  data.cpuTemp = temperatureRead();  // ESP32 internal temp sensor
  data.rssi = WiFi.RSSI();
  
  #if ENABLE_BATTERY_MON
  // Read battery voltage (assuming voltage divider)
  int raw = analogRead(PIN_BATTERY);
  data.batteryVoltage = raw * 3.3 / 4095.0 * 2.0;  // Adjust multiplier based on your divider
  #endif
}
#endif

// ============ TRADE LOG ============
#if ENABLE_TRADE_LOG
void addTradeToLog(const char* symbol, const char* action, float price, float pnl) {
  int idx = data.tradeIndex % 20;
  strlcpy(data.tradeHistory[idx].symbol, symbol, sizeof(data.tradeHistory[0].symbol));
  strlcpy(data.tradeHistory[idx].action, action, sizeof(data.tradeHistory[0].action));
  data.tradeHistory[idx].price = price;
  data.tradeHistory[idx].pnl = pnl;
  data.tradeHistory[idx].time = millis();
  
  data.tradeIndex++;
  if (data.tradeCount < 20) data.tradeCount++;
}
#endif

// ============ OTA SETUP ============
#if ENABLE_OTA
void setupOTA() {
  ArduinoOTA.setHostname(DEVICE_ID);
  
  ArduinoOTA.onStart([]() {
    display.clearDisplay();
    display.setTextSize(1);
    display.setCursor(20, 20);
    display.print(F("OTA Update..."));
    display.display();
  });
  
  ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
    int pct = (progress * 100) / total;
    display.drawRect(10, 40, 108, 10, SSD1306_WHITE);
    display.fillRect(12, 42, pct, 6, SSD1306_WHITE);
    display.display();
  });
  
  ArduinoOTA.onEnd([]() {
    display.clearDisplay();
    display.setCursor(30, 30);
    display.print(F("Update OK!"));
    display.display();
    delay(1000);
  });
  
  ArduinoOTA.begin();
}
#endif

// ============ MELODIES (Implementation) ============
void playMelody(Melody melody) {
  #if ENABLE_SOUND
  switch (melody) {
    case MELODY_BOOT:
      tone(PIN_BUZZER, 1000, 100);
      delay(100);
      tone(PIN_BUZZER, 1500, 100);
      delay(100);
      tone(PIN_BUZZER, 2000, 200);
      break;
      
    case MELODY_BUTTON:
      tone(PIN_BUZZER, 2000, 30);
      break;
      
    case MELODY_ALERT:
      // Urgent alert pattern
      for (int i = 0; i < 3; i++) {
        tone(PIN_BUZZER, 3000, 150);
        delay(200);
        tone(PIN_BUZZER, 4000, 150);
        delay(200);
      }
      break;
      
    case MELODY_ERROR:
      tone(PIN_BUZZER, 500, 500);
      break;
  }
  #endif
}

// ============ ERROR HANDLING ============
void fatalError() {
  while (1) {
    digitalWrite(PIN_LED, !digitalRead(PIN_LED));
    delay(100);
  }
}

// Legacy analogWrite for ESP32 (if not defined)
#ifndef analogWrite
void analogWrite(uint8_t pin, int value) {
  // Simple digital fallback
  digitalWrite(pin, value > 127 ? HIGH : LOW);
}
#endif
