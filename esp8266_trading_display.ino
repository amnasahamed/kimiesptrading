/*
  ESP8266 Trading Bot - Optimized for 1.3" 128x64 OLED
  =====================================================
  Hardware: ESP8266 + 1.3" I2C OLED (SSD1306, 4-pin)
  
  Features:
  - Fast 150ms button response
  - Clean, information-dense layouts
  - No animation delays
  - 30fps refresh for snappy UI
  - 4 screens: Dashboard | Positions | Stats | Settings
*/

#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>
#include <WiFiClientSecure.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

// ============ CONFIG ============
const char* ssid = "YOUR_WIFI_SSID";
const char* password = "YOUR_WIFI_PASSWORD";
const char* serverUrl = "https://coolify.themelon.in";

// Pins (NodeMCU D1 Mini mapping)
// NOTE: Use D6 (GPIO12) for button, NOT D3 (GPIO0) which is Flash button
#define BUTTON_PIN 12     // D6 - External button (GPIO12 is safe)
#define LED_PIN 2         // D4 - Built-in LED (Active LOW)
#define BUZZER_PIN 14     // D5 - Optional buzzer
#define SDA_PIN 4         // D2 - OLED SDA
#define SCL_PIN 5         // D1 - OLED SCL

// OLED
#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
#define OLED_RESET -1
#define OLED_ADDR 0x3C    // Common for 1.3" OLEDs (try 0x3D if not working)

Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

// ============ DATA STRUCTURES ============
struct TradingData {
  bool systemEnabled;
  bool marketOpen;
  bool paperTrading;
  float todayPnl;
  float winRate;
  int openPositions;
  int todayTrades;
  int maxTrades;
  char symbol1[12];
  float pnl1;
  int qty1;
};

struct AlertData {
  bool active;
  char symbol[12];
  float price;
  unsigned long showTime;
};

TradingData data = {false, false, true, 0, 0, 0, 0, 10, "", 0, 0};
AlertData alert = {false, "", 0, 0};

// Screens
enum Screen { SCR_DASHBOARD, SCR_POSITIONS, SCR_STATS, SCR_COUNT };
Screen currentScreen = SCR_DASHBOARD;
const char* screenNames[] = {"DASHBOARD", "POSITIONS", "STATS"};

// Timing
unsigned long lastDataFetch = 0;
unsigned long lastAlertCheck = 0;
unsigned long lastDisplayUpdate = 0;
const unsigned long DATA_INTERVAL = 3000;
const unsigned long ALERT_INTERVAL = 1000;
const unsigned long DISPLAY_INTERVAL = 33; // ~30fps

// Button state machine
enum ButtonState { BTN_IDLE, BTN_DEBOUNCING, BTN_PRESSED, BTN_WAIT_RELEASE };
ButtonState btnState = BTN_IDLE;
unsigned long btnTimer = 0;
const unsigned long BTN_DEBOUNCE_MS = 50;   // 50ms debounce
const unsigned long BTN_COOLDOWN_MS = 200;  // 200ms between presses

// Debug counter
int btnPressCount = 0;

// ============ SETUP ============
void setup() {
  Serial.begin(115200);
  
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  pinMode(LED_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  
  // Init OLED with specific I2C pins at 400kHz for faster refresh
  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(400000); // 400kHz I2C (default is 100kHz)
  
  if(!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
    Serial.println(F("SSD1306 allocation failed"));
    // Blink LED forever
    while(1) {
      digitalWrite(LED_PIN, !digitalRead(LED_PIN));
      delay(100);
    }
  }
  
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.display();
  
  // Quick splash (no animation delays)
  showSplash();
  
  // Connect WiFi
  connectWiFi();
  
  // Initial data fetch
  fetchData();
  
  Serial.println(F("Ready!"));
}

// ============ MAIN LOOP ============
void loop() {
  unsigned long now = millis();
  
  // Handle button with fast debounce
  handleButton();
  
  // Update LED indicator
  updateLED();
  
  // Fetch trading data every 3 seconds
  if (now - lastDataFetch > DATA_INTERVAL) {
    fetchData();
    lastDataFetch = now;
  }
  
  // Check for alerts every second
  if (now - lastAlertCheck > ALERT_INTERVAL) {
    checkAlerts();
    lastAlertCheck = now;
  }
  
  // Update display at 30fps
  if (now - lastDisplayUpdate > DISPLAY_INTERVAL) {
    updateDisplay();
    lastDisplayUpdate = now;
  }
  
  // Alert timeout (10 seconds)
  if (alert.active && now - alert.showTime > 10000) {
    alert.active = false;
  }
}

// ============ DISPLAY SCREENS ============
void updateDisplay() {
  display.clearDisplay();
  
  if (alert.active) {
    drawAlert();
  } else {
    switch (currentScreen) {
      case SCR_DASHBOARD: drawDashboard(); break;
      case SCR_POSITIONS: drawPositions(); break;
      case SCR_STATS: drawStats(); break;
    }
  }
  
  display.display();
}

void drawDashboard() {
  // === TOP BAR (12px height) ===
  // Mode indicator (left)
  display.fillRect(0, 0, 34, 12, SSD1306_WHITE);
  display.setTextColor(SSD1306_BLACK);
  display.setTextSize(1);
  display.setCursor(2, 2);
  display.print(data.paperTrading ? "DEMO" : "LIVE");
  
  // WiFi icon (right side of top bar)
  drawWiFiIcon(90, 2);
  
  // System status indicator (far right)
  if (data.systemEnabled && data.marketOpen) {
    // Green dot simulation (filled circle)
    display.fillCircle(122, 6, 3, SSD1306_WHITE);
  } else {
    display.drawCircle(122, 6, 3, SSD1306_WHITE);
  }
  
  // === MAIN P&L DISPLAY (center, large) ===
  display.setTextColor(SSD1306_WHITE);
  
  // P&L Label
  display.setTextSize(1);
  display.setCursor(4, 16);
  display.print("TODAY'S P&L");
  
  // P&L Value - BIG (use entire width)
  display.setTextSize(3);
  String pnlStr = formatCurrency(data.todayPnl);
  int textWidth = pnlStr.length() * 18; // Size 3 = 18px per char
  int startX = (128 - textWidth) / 2;
  if (startX < 0) startX = 0;
  
  display.setCursor(startX, 28);
  if (data.todayPnl >= 0) {
    display.print("+");
  } else {
    display.print("-");
  }
  display.print("");
  display.print(String(abs((int)data.todayPnl)));
  
  // === BOTTOM INFO BAR ===
  // Horizontal separator
  display.drawLine(0, 52, 128, 52, SSD1306_WHITE);
  
  // Left: Trade count
  display.setTextSize(1);
  display.setCursor(4, 55);
  display.print(data.todayTrades);
  display.print("/");
  display.print(data.maxTrades);
  display.print(" TRADES");
  
  // Right: Status text
  display.setCursor(90, 55);
  if (!data.systemEnabled) {
    display.print("OFF");
  } else if (!data.marketOpen) {
    display.print("CLOSED");
  } else {
    // Animated dots for active
    int dots = (millis() / 400) % 4;
    display.print("LIVE");
    for (int i = 0; i < dots; i++) display.print(".");
  }
  
  // Page indicator (bottom dots)
  drawPageIndicator(0);
}

void drawPositions() {
  // Header bar
  display.fillRect(0, 0, 128, 11, SSD1306_WHITE);
  display.setTextColor(SSD1306_BLACK);
  display.setTextSize(1);
  display.setCursor(2, 1);
  display.print("POSITIONS");
  display.setCursor(80, 1);
  display.print("(");
  display.print(data.openPositions);
  display.print(")");
  
  display.setTextColor(SSD1306_WHITE);
  
  if (data.openPositions == 0) {
    // Clean "No positions" message
    display.setCursor(20, 28);
    display.print("No open positions");
    display.setCursor(15, 42);
    display.print("Waiting for signals...");
  } else {
    // Table header
    display.setTextSize(1);
    display.setCursor(0, 14);
    display.print("SYMBOL");
    display.setCursor(60, 14);
    display.print("QTY");
    display.setCursor(90, 14);
    display.print("P&L");
    display.drawLine(0, 23, 128, 23, SSD1306_WHITE);
    
    // Position rows (up to 3 positions fit well)
    int yPos = 26;
    display.setCursor(0, yPos);
    display.print(data.symbol1[0] ? data.symbol1 : "RELIANCE");
    display.setCursor(62, yPos);
    display.print(data.qty1 ? data.qty1 : 10);
    display.setCursor(90, yPos);
    float pnl = data.pnl1 ? data.pnl1 : 1250;
    if (pnl >= 0) {
      display.print("+");
      display.print((int)pnl);
    } else {
      display.print((int)pnl);
    }
    
    // Show message if more positions
    if (data.openPositions > 1) {
      display.setCursor(0, 40);
      display.print("+");
      display.print(data.openPositions - 1);
      display.print(" more on app...");
    }
  }
  
  drawPageIndicator(1);
}

void drawStats() {
  // Header bar
  display.fillRect(0, 0, 128, 11, SSD1306_WHITE);
  display.setTextColor(SSD1306_BLACK);
  display.setTextSize(1);
  display.setCursor(2, 1);
  display.print("STATISTICS");
  
  display.setTextColor(SSD1306_WHITE);
  
  // Win Rate - Big number left side
  display.setTextSize(1);
  display.setCursor(4, 16);
  display.print("WIN RATE");
  
  display.setTextSize(3);
  display.setCursor(4, 28);
  display.print((int)data.winRate);
  display.setTextSize(2);
  display.print("%");
  
  // Vertical separator
  display.drawLine(70, 16, 70, 50, SSD1306_WHITE);
  
  // Stats column on right
  display.setTextSize(1);
  
  // Total Trades
  display.setCursor(76, 18);
  display.print("TTL:");
  display.print(data.todayTrades);
  
  // Open Positions
  display.setCursor(76, 28);
  display.print("OPEN:");
  display.print(data.openPositions);
  
  // P&L
  display.setCursor(76, 38);
  display.print("P&L:");
  if (data.todayPnl >= 0) display.print("+");
  display.print((int)data.todayPnl);
  
  // Connection
  display.setCursor(76, 48);
  display.print("WIFI:");
  display.print(WiFi.status() == WL_CONNECTED ? "OK" : "--");
  
  drawPageIndicator(2);
}

void drawAlert() {
  // Flashing border effect
  bool flash = (millis() / 150) % 2;
  
  if (flash) {
    display.fillRect(0, 0, 128, 64, SSD1306_WHITE);
    display.setTextColor(SSD1306_BLACK);
  } else {
    display.setTextColor(SSD1306_WHITE);
  }
  
  // Double border
  display.drawRect(2, 2, 124, 60, flash ? SSD1306_BLACK : SSD1306_WHITE);
  display.drawRect(4, 4, 120, 56, flash ? SSD1306_BLACK : SSD1306_WHITE);
  
  // Header
  display.setTextSize(1);
  display.setCursor(35, 8);
  display.print("NEW ALERT!");
  
  // Symbol name - LARGE
  display.setTextSize(2);
  int symWidth = strlen(alert.symbol) * 12;
  int symX = (128 - symWidth) / 2;
  if (symX < 10) symX = 10;
  display.setCursor(symX, 24);
  display.print(alert.symbol);
  
  // Price
  display.setTextSize(1);
  display.setCursor(30, 44);
  display.print("@ Rs");
  display.print(alert.price, 1);
  
  // Dismiss instruction
  display.setCursor(20, 56);
  display.print("Press btn to dismiss");
}

// ============ DRAW HELPERS ============
void drawWiFiIcon(int x, int y) {
  // Simple 3-arc WiFi icon
  display.drawPixel(x + 2, y + 4, SSD1306_BLACK);
  display.drawLine(x + 1, y + 3, x + 3, y + 3, SSD1306_BLACK);
  display.drawLine(x, y + 2, x + 4, y + 2, SSD1306_BLACK);
  display.drawLine(x, y + 1, x + 4, y + 1, SSD1306_BLACK);
}

void drawPageIndicator(int activePage) {
  // 3 dots at bottom center
  int startX = 58;
  int y = 62;
  
  for (int i = 0; i < 3; i++) {
    if (i == activePage) {
      display.fillRect(startX + (i * 8), y, 5, 2, SSD1306_WHITE);
    } else {
      display.drawPixel(startX + (i * 8) + 2, y + 1, SSD1306_WHITE);
    }
  }
}

String formatCurrency(float value) {
  String result = "Rs";
  result += String(abs((int)value));
  return result;
}

void showSplash() {
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  
  // Logo icon (target/bullseye)
  display.fillCircle(24, 22, 10, SSD1306_WHITE);
  display.fillCircle(24, 22, 7, SSD1306_BLACK);
  display.fillCircle(24, 22, 4, SSD1306_WHITE);
  display.fillCircle(24, 22, 2, SSD1306_BLACK);
  
  // Title
  display.setTextSize(2);
  display.setCursor(44, 14);
  display.print("MELON");
  
  // Subtitle
  display.setTextSize(1);
  display.setCursor(44, 32);
  display.print("Trading Bot");
  
  // Version/connector
  display.setCursor(44, 44);
  display.print("1.3 OLED");
  
  // Loading bar outline
  display.drawRect(10, 56, 108, 6, SSD1306_WHITE);
  display.display();
  
  // Quick fill animation (just 5 frames)
  for (int i = 0; i <= 100; i += 25) {
    display.fillRect(12, 58, i, 2, SSD1306_WHITE);
    display.display();
    delay(50);
  }
  delay(200);
}

// ============ INPUT ============
void handleButton() {
  bool rawState = digitalRead(BUTTON_PIN);
  unsigned long now = millis();
  
  switch (btnState) {
    case BTN_IDLE:
      // Waiting for press (LOW = pressed with INPUT_PULLUP)
      if (rawState == LOW) {
        btnState = BTN_DEBOUNCING;
        btnTimer = now;
        Serial.println(F("[BTN] Press detected, debouncing..."));
      }
      break;
      
    case BTN_DEBOUNCING:
      // Wait for debounce period
      if (now - btnTimer >= BTN_DEBOUNCE_MS) {
        // Check if still pressed
        if (digitalRead(BUTTON_PIN) == LOW) {
          btnState = BTN_PRESSED;
          btnPressCount++;
          Serial.print(F("[BTN] CONFIRMED PRESS #"));
          Serial.println(btnPressCount);
          
          // EXECUTE ACTION
          if (alert.active) {
            alert.active = false;
            Serial.println(F("[BTN] Dismissed alert"));
          } else {
            currentScreen = (Screen)((currentScreen + 1) % SCR_COUNT);
            Serial.print(F("[BTN] Screen -> "));
            Serial.println(screenNames[currentScreen]);
          }
          
          // Feedback
          tone(BUZZER_PIN, 2000, 30);
          updateDisplay();
          
          btnState = BTN_WAIT_RELEASE;
        } else {
          // False alarm (noise/bounce)
          Serial.println(F("[BTN] Debounce failed - noise"));
          btnState = BTN_IDLE;
        }
      }
      break;
      
    case BTN_PRESSED:
      // Shouldn't happen, go to wait release
      btnState = BTN_WAIT_RELEASE;
      break;
      
    case BTN_WAIT_RELEASE:
      // Wait for button to be released + cooldown
      if (rawState == HIGH) {
        if (now - btnTimer >= BTN_COOLDOWN_MS) {
          Serial.println(F("[BTN] Ready for next press"));
          btnState = BTN_IDLE;
        }
      } else {
        // Still held, reset cooldown timer
        btnTimer = now;
      }
      break;
  }
}

// ============ LED CONTROL ============
void updateLED() {
  // LED is inverted on NodeMCU (LOW = ON, HIGH = OFF)
  if (!data.systemEnabled) {
    digitalWrite(LED_PIN, HIGH); // OFF
  } else if (alert.active) {
    // Fast blink for alert
    digitalWrite(LED_PIN, (millis() / 100) % 2 ? LOW : HIGH);
  } else if (data.todayPnl > 0) {
    digitalWrite(LED_PIN, LOW); // Solid ON for profit
  } else if (data.todayPnl < 0) {
    // Slow blink for loss
    digitalWrite(LED_PIN, (millis() / 500) % 2 ? LOW : HIGH);
  } else {
    // Very slow for neutral
    digitalWrite(LED_PIN, (millis() / 1000) % 2 ? LOW : HIGH);
  }
}

// ============ NETWORK ============
void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);
  
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 50) {
    delay(100);
    digitalWrite(LED_PIN, attempts % 2 ? LOW : HIGH);
    attempts++;
  }
  
  // Connected or timeout
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print(F("WiFi IP: "));
    Serial.println(WiFi.localIP());
  }
}

void fetchData() {
  if (WiFi.status() != WL_CONNECTED) return;
  
  WiFiClientSecure client;
  client.setInsecure();
  HTTPClient http;
  
  http.begin(client, String(serverUrl) + "/api/esp/stats");
  http.setTimeout(500); // 500ms max - keep UI responsive
  http.addHeader("Content-Type", "application/json");
  
  int code = http.GET();
  if (code == 200) {
    DynamicJsonDocument doc(1024); // Heap allocation to avoid stack overflow
    DeserializationError error = deserializeJson(doc, http.getString());
    
    if (!error) {
      data.systemEnabled = doc["system_enabled"] | false;
      data.marketOpen = doc["market_open"] | false;
      data.paperTrading = doc["paper_trading"] | true;
      data.todayPnl = doc["today_pnl"] | 0.0;
      data.winRate = doc["win_rate"] | 0.0;
      data.openPositions = doc["open_positions"] | 0;
      data.todayTrades = doc["today_trades"] | 0;
      data.maxTrades = doc["max_trades"] | 10;
      
      // Parse first position if available
      JsonArray positions = doc["positions"];
      if (positions && positions.size() > 0) {
        JsonObject pos = positions[0];
        strlcpy(data.symbol1, pos["symbol"] | "", sizeof(data.symbol1));
        data.qty1 = pos["quantity"] | 0;
        data.pnl1 = pos["pnl"] | 0.0;
      }
    }
  }
  
  http.end();
}

void checkAlerts() {
  if (WiFi.status() != WL_CONNECTED) return;
  
  WiFiClientSecure client;
  client.setInsecure();
  HTTPClient http;
  
  http.begin(client, String(serverUrl) + "/api/esp/alert");
  http.setTimeout(500); // 500ms max
  
  int code = http.GET();
  if (code == 200) {
    DynamicJsonDocument doc(512); // Heap allocation
    DeserializationError error = deserializeJson(doc, http.getString());
    
    if (!error && doc["new_alert"] == true) {
      strlcpy(alert.symbol, doc["symbol"] | "UNKNOWN", sizeof(alert.symbol));
      alert.price = doc["price"] | 0.0;
      alert.active = true;
      alert.showTime = millis();
      
      // Alert sound (double beep)
      tone(BUZZER_PIN, 3000, 100);
      delay(100);
      tone(BUZZER_PIN, 4000, 200);
    }
  }
  
  http.end();
}
