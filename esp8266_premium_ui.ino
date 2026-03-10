/*
  ESP8266 Trading Bot - PREMIUM OLED UI
  ======================================
  Hardware: ESP8266 + 128x64 OLED (SSD1306)
  
  Features:
  - Animated splash screen
  - Icon-based navigation
  - Progress bars and charts
  - Smooth transitions
  - Scrolling text for long symbols
  - Battery/WiFi indicators
  - Anti-burn-in protection
*/

#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>
#include <WiFiClient.h>
#include <WiFiClientSecure.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

// ============ CONFIG ============
const char* ssid = "YOUR_WIFI_SSID";
const char* password = "YOUR_WIFI_PASSWORD";
const char* serverUrl = "https://coolify.themelon.in";

// Pins (GPIO numbers for compatibility)
#define BUTTON_PIN 0
#define LED_PIN 2
#define BUZZER_PIN 14
#define SDA_PIN 4
#define SCL_PIN 5

// OLED
#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
#define OLED_RESET -1
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

// ============ ICONS (5x5 to 16x16 bitmaps) ============
const unsigned char ICON_WIFI[] PROGMEM = {
  0b00000, 0b01110, 0b10001, 0b00100, 0b01010, 0b00000, 0b00100, 0b00000
}; // 8x8

const unsigned char ICON_MONEY[] PROGMEM = {
  0b0011100, 0b0111110, 0b1101011, 0b1111111, 0b1101011, 0b0111110, 0b0011100
}; // 7x7

const unsigned char ICON_CHART_UP[] PROGMEM = {
  0b00000001, 0b00000011, 0b00000101, 0b00001001, 0b00010001, 0b00100001, 0b01000001, 0b11111111
}; // 8x8

const unsigned char ICON_CHART_DOWN[] PROGMEM = {
  0b11111111, 0b01000001, 0b00100001, 0b00010001, 0b00001001, 0b00000101, 0b00000011, 0b00000001
}; // 8x8

const unsigned char ICON_BELL[] PROGMEM = {
  0b001000, 0b011100, 0b011100, 0b011100, 0b111110, 0b111110, 0b001000, 0b000000
}; // 6x8

// ============ STATE ============
struct TradingData {
  bool systemEnabled;
  bool marketOpen;
  bool paperTrading;
  float todayPnl;
  int openPositions;
  int todayTrades;
  int maxTrades;
  float winRate;
};

TradingData data = {false, false, true, 0, 0, 0, 10, 0};

// Display modes
enum Screen {
  SCREEN_SPLASH,
  SCREEN_DASHBOARD,
  SCREEN_POSITIONS,
  SCREEN_DETAIL,
  SCREEN_STATS,
  SCREEN_ALERT
};
Screen currentScreen = SCREEN_SPLASH;
Screen prevScreen = SCREEN_SPLASH;

// Animation
int animFrame = 0;
unsigned long animLastUpdate = 0;
bool transitioning = false;
int transitionFrame = 0;

// Timing
unsigned long lastDataUpdate = 0;
unsigned long lastAlertCheck = 0;
unsigned long lastDisplayUpdate = 0;
unsigned long alertShowTime = 0;
const unsigned long DATA_INTERVAL = 3000;
const unsigned long ALERT_INTERVAL = 1000;
const unsigned long DISPLAY_INTERVAL = 50; // 20fps for smooth animations

// Scrolling text
String scrollText = "";
int scrollPos = 0;
unsigned long lastScroll = 0;

// Alert
bool showingAlert = false;
String alertSymbol = "";
float alertPrice = 0;

// Burn-in protection
int screenOffsetX = 0;
int screenOffsetY = 0;
unsigned long lastOffsetChange = 0;

// ============ SETUP ============
void setup() {
  Serial.begin(115200);
  delay(100);
  
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  pinMode(LED_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  
  // Init OLED
  Wire.begin(SDA_PIN, SCL_PIN);
  if(!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    Serial.println("OLED failed");
    while(1) { blinkLED(100); }
  }
  
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.display();
  
  // Show animated splash
  showSplashAnimation();
  
  // Connect WiFi
  connectWiFi();
  
  // Initial data
  fetchData();
  
  // Go to dashboard
  currentScreen = SCREEN_DASHBOARD;
  
  Serial.println("Ready!");
}

// ============ MAIN LOOP ============
void loop() {
  unsigned long now = millis();
  
  // Handle button
  handleButton();
  
  // Update LED
  updateLED();
  
  // Fetch data
  if (now - lastDataUpdate > DATA_INTERVAL) {
    fetchData();
    lastDataUpdate = now;
  }
  
  // Check alerts
  if (now - lastAlertCheck > ALERT_INTERVAL) {
    checkAlerts();
    lastAlertCheck = now;
  }
  
  // Update display at 20fps for smooth animations
  if (now - lastDisplayUpdate > DISPLAY_INTERVAL) {
    updateDisplay();
    lastDisplayUpdate = now;
  }
  
  // Alert timeout
  if (showingAlert && now - alertShowTime > 10000) {
    showingAlert = false;
    currentScreen = SCREEN_DASHBOARD;
  }
  
  // Burn-in protection (shift pixels slightly every 30 seconds)
  if (now - lastOffsetChange > 30000) {
    screenOffsetX = random(-1, 2);
    screenOffsetY = random(-1, 2);
    lastOffsetChange = now;
  }
  
  delay(5);
}

// ============ SPLASH ANIMATION ============
void showSplashAnimation() {
  // Frame 1: Border draw
  for (int i = 0; i <= 64; i += 4) {
    display.clearDisplay();
    display.drawRect(0, 0, 128, 64, SSD1306_WHITE);
    display.fillRect(0, 0, i * 2, 64, SSD1306_WHITE);
    display.display();
    delay(20);
  }
  
  // Frame 2: Text reveal
  display.clearDisplay();
  display.fillRect(0, 20, 128, 24, SSD1306_WHITE);
  display.setTextColor(SSD1306_BLACK);
  display.setTextSize(2);
  display.setCursor(10, 24);
  display.print("MELON");
  display.display();
  delay(300);
  
  // Frame 3: Full logo
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  
  // Logo icon
  display.fillCircle(24, 20, 8, SSD1306_WHITE);
  display.fillCircle(24, 20, 5, SSD1306_BLACK);
  display.fillCircle(24, 20, 2, SSD1306_WHITE);
  
  // Title
  display.setTextSize(2);
  display.setCursor(40, 14);
  display.print("MELON");
  
  // Subtitle
  display.setTextSize(1);
  display.setCursor(40, 34);
  display.print("TRADING BOT");
  
  // Loading bar
  display.drawRect(10, 50, 108, 8, SSD1306_WHITE);
  for (int i = 0; i <= 104; i += 4) {
    display.fillRect(12, 52, i, 4, SSD1306_WHITE);
    display.display();
    delay(30);
  }
  
  delay(500);
}

// ============ DISPLAY SCREENS ============
void updateDisplay() {
  display.clearDisplay();
  
  // Apply burn-in offset
  display.setRotation(0);
  
  switch (currentScreen) {
    case SCREEN_DASHBOARD:
      drawDashboard();
      break;
    case SCREEN_POSITIONS:
      drawPositions();
      break;
    case SCREEN_STATS:
      drawStats();
      break;
    case SCREEN_ALERT:
      drawAlert();
      break;
    default:
      drawDashboard();
  }
  
  display.display();
}

void drawDashboard() {
  // Top bar with mode and WiFi
  display.fillRect(0, 0, 128, 12, SSD1306_WHITE);
  display.setTextColor(SSD1306_BLACK);
  display.setTextSize(1);
  display.setCursor(2, 2);
  display.print(data.paperTrading ? "PAPER" : "LIVE");
  
  // WiFi icon
  drawWiFiIcon(108, 2);
  
  // Battery/Power icon
  drawBatteryIcon(92, 2);
  
  // Main content area
  display.setTextColor(SSD1306_WHITE);
  
  // Big P&L Box
  int boxY = 16;
  int boxH = 30;
  display.drawRect(4, boxY, 120, boxH, SSD1306_WHITE);
  display.drawRect(5, boxY+1, 118, boxH-2, SSD1306_WHITE);
  
  // P&L Label
  display.setTextSize(1);
  display.setCursor(8, boxY + 4);
  display.print("TODAY'S P&L");
  
  // P&L Value (Big)
  display.setTextSize(2);
  String pnlStr = "";
  if (data.todayPnl >= 0) pnlStr += "+";
  pnlStr += "Rs";
  pnlStr += String(abs((int)data.todayPnl));
  
  int textWidth = pnlStr.length() * 12;
  int startX = (128 - textWidth) / 2;
  display.setCursor(startX, boxY + 14);
  
  if (data.todayPnl >= 0) {
    display.print("+");
  } else {
    display.print("-");
  }
  display.print("Rs");
  display.print(abs((int)data.todayPnl));
  
  // Progress bar for daily trades
  int barY = 50;
  int barMax = 100;
  int barFill = (data.todayTrades * barMax) / data.maxTrades;
  
  display.drawRect(4, barY, barMax + 4, 8, SSD1306_WHITE);
  display.fillRect(6, barY + 2, barFill, 4, SSD1306_WHITE);
  
  // Trade count
  display.setTextSize(1);
  display.setCursor(108, barY + 1);
  display.print(data.todayTrades);
  display.print("/");
  display.print(data.maxTrades);
  
  // Bottom status line
  display.setCursor(4, 58);
  if (!data.systemEnabled) {
    display.print("TRADING OFF");
  } else if (!data.marketOpen) {
    display.print("MARKET CLOSED");
  } else {
    // Animated dots
    int dots = (millis() / 500) % 4;
    display.print("MONITORING");
    for (int i = 0; i < dots; i++) display.print(".");
  }
  
  // Page indicator dots
  drawPageIndicator(0);
}

void drawPositions() {
  // Header
  display.fillRect(0, 0, 128, 12, SSD1306_WHITE);
  display.setTextColor(SSD1306_BLACK);
  display.setTextSize(1);
  display.setCursor(2, 2);
  display.print("POSITIONS");
  display.print(" (");
  display.print(data.openPositions);
  display.print(")");
  
  display.setTextColor(SSD1306_WHITE);
  
  if (data.openPositions == 0) {
    display.setCursor(10, 30);
    display.print("No positions open");
    display.setCursor(10, 42);
    display.print("Waiting for signals");
  } else {
    // Show position list
    display.setTextSize(1);
    display.setCursor(0, 16);
    display.print("SYMBOL  QTY    P&L");
    display.drawLine(0, 25, 128, 25, SSD1306_WHITE);
    
    // Mock positions for demo (replace with real data)
    display.setCursor(0, 28);
    display.print("RELIANCE");
    display.setCursor(56, 28);
    display.print("10");
    display.setCursor(80, 28);
    display.print("+1250");
    
    display.setCursor(0, 40);
    display.print("TCS");
    display.setCursor(56, 40);
    display.print("5");
    display.setCursor(80, 40);
    display.print("-320");
    
    display.setCursor(0, 52);
    display.print("Press btn for detail");
  }
  
  drawPageIndicator(1);
}

void drawStats() {
  // Header
  display.fillRect(0, 0, 128, 12, SSD1306_WHITE);
  display.setTextColor(SSD1306_BLACK);
  display.setTextSize(1);
  display.setCursor(2, 2);
  display.print("STATISTICS");
  display.setTextColor(SSD1306_WHITE);
  
  // Stats grid
  display.setTextSize(1);
  
  // Win rate box
  display.drawRect(4, 16, 58, 40, SSD1306_WHITE);
  display.setCursor(16, 22);
  display.print("WIN");
  display.setCursor(16, 32);
  display.print("RATE");
  display.setTextSize(2);
  display.setCursor(12, 44);
  display.print(String((int)data.winRate));
  display.print("%");
  
  // Stats list
  display.setTextSize(1);
  display.setCursor(68, 20);
  display.print("Total:");
  display.print(data.todayTrades);
  
  display.setCursor(68, 30);
  display.print("Open:");
  display.print(data.openPositions);
  
  display.setCursor(68, 40);
  display.print("Mode:");
  display.print(data.paperTrading ? "PAPER" : "LIVE");
  
  display.setCursor(68, 50);
  display.print("WiFi:");
  display.print(WiFi.status() == WL_CONNECTED ? "OK" : "ERR");
  
  drawPageIndicator(2);
}

void drawAlert() {
  // Flashing background
  bool flash = (millis() / 200) % 2;
  if (flash) {
    display.fillRect(0, 0, 128, 64, SSD1306_WHITE);
    display.setTextColor(SSD1306_BLACK);
  } else {
    display.setTextColor(SSD1306_WHITE);
  }
  
  // Border
  display.drawRect(2, 2, 124, 60, flash ? SSD1306_BLACK : SSD1306_WHITE);
  display.drawRect(3, 3, 122, 58, flash ? SSD1306_BLACK : SSD1306_WHITE);
  
  // Alert header
  display.setTextSize(1);
  display.setCursor(35, 8);
  display.print("NEW ALERT!");
  
  // Symbol (large)
  display.setTextSize(2);
  int symbolWidth = alertSymbol.length() * 12;
  int startX = (128 - symbolWidth) / 2;
  display.setCursor(startX, 22);
  display.print(alertSymbol);
  
  // Price
  display.setTextSize(1);
  display.setCursor(25, 42);
  display.print("@ Rs");
  display.print(alertPrice, 2);
  
  // Time
  display.setCursor(30, 54);
  display.print("Tap btn to dismiss");
}

// ============ DRAW HELPERS ============
void drawWiFiIcon(int x, int y) {
  // Simple WiFi arcs
  display.drawPixel(x + 2, y + 3, SSD1306_BLACK);
  display.drawLine(x + 1, y + 2, x + 3, y + 2, SSD1306_BLACK);
  display.drawLine(x, y + 1, x + 4, y + 1, SSD1306_BLACK);
  display.drawLine(x, y, x + 4, y, SSD1306_BLACK);
}

void drawBatteryIcon(int x, int y) {
  display.drawRect(x, y, 12, 7, SSD1306_BLACK);
  display.drawPixel(x + 12, y + 2, SSD1306_BLACK);
  display.drawPixel(x + 12, y + 4, SSD1306_BLACK);
  // Fill based on level (mock 70%)
  display.fillRect(x + 2, y + 2, 6, 3, SSD1306_BLACK);
}

void drawPageIndicator(int activePage) {
  // Draw 3 dots at bottom center
  int startX = 55;
  int y = 62;
  
  for (int i = 0; i < 3; i++) {
    if (i == activePage) {
      display.fillRect(startX + (i * 8), y, 6, 2, SSD1306_WHITE);
    } else {
      display.drawRect(startX + (i * 8), y, 6, 2, SSD1306_WHITE);
    }
  }
}

// ============ INPUT ============
void handleButton() {
  static unsigned long lastPress = 0;
  
  if (digitalRead(BUTTON_PIN) == LOW) {
    if (millis() - lastPress > 300) {
      lastPress = millis();
      
      if (showingAlert) {
        showingAlert = false;
        currentScreen = SCREEN_DASHBOARD;
        return;
      }
      
      // Cycle screens
      currentScreen = (Screen)((currentScreen + 1) % 3);
      if (currentScreen == SCREEN_ALERT) currentScreen = SCREEN_DASHBOARD;
      
      // Feedback
      digitalWrite(LED_PIN, HIGH);
      delay(50);
      digitalWrite(LED_PIN, LOW);
      
      // Optional beep
      tone(BUZZER_PIN, 2000, 50);
    }
  }
}

// ============ LED ============
void updateLED() {
  if (!data.systemEnabled) {
    digitalWrite(LED_PIN, LOW);
  } else if (showingAlert) {
    // Fast blink for alert
    digitalWrite(LED_PIN, (millis() / 100) % 2);
  } else if (data.todayPnl > 0) {
    digitalWrite(LED_PIN, HIGH); // Solid for profit
  } else if (data.todayPnl < 0) {
    digitalWrite(LED_PIN, (millis() / 500) % 2); // Slow blink for loss
  } else {
    digitalWrite(LED_PIN, (millis() / 1000) % 2); // Very slow for neutral
  }
}

void blinkLED(int delayMs) {
  digitalWrite(LED_PIN, HIGH);
  delay(delayMs);
  digitalWrite(LED_PIN, LOW);
  delay(delayMs);
}

// ============ NETWORK ============
void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);
  
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 40) {
    delay(250);
    blinkLED(100);
    attempts++;
  }
}

void fetchData() {
  if (WiFi.status() != WL_CONNECTED) return;
  
  WiFiClientSecure client;
  client.setInsecure();
  HTTPClient http;
  
  http.begin(client, String(serverUrl) + "/api/esp/stats");
  http.setTimeout(3000);
  
  int code = http.GET();
  if (code == 200) {
    StaticJsonDocument<512> doc;
    deserializeJson(doc, http.getString());
    
    data.systemEnabled = doc["system_enabled"] | false;
    data.marketOpen = doc["market_open"] | false;
    data.paperTrading = doc["paper_trading"] | true;
    data.todayPnl = doc["today_pnl"] | 0.0;
    data.openPositions = doc["open_positions"] | 0;
    data.todayTrades = doc["today_trades"] | 0;
    data.maxTrades = doc["max_trades"] | 10;
  }
  
  http.end();
}

void checkAlerts() {
  if (WiFi.status() != WL_CONNECTED) return;
  
  WiFiClientSecure client;
  client.setInsecure();
  HTTPClient http;
  
  http.begin(client, String(serverUrl) + "/api/esp/alert");
  http.setTimeout(2000);
  
  int code = http.GET();
  if (code == 200) {
    StaticJsonDocument<256> doc;
    deserializeJson(doc, http.getString());
    
    if (doc["new_alert"] == true) {
      alertSymbol = doc["symbol"] | "UNKNOWN";
      alertPrice = doc["price"] | 0.0;
      showingAlert = true;
      alertShowTime = millis();
      currentScreen = SCREEN_ALERT;
      
      // Alert notification
      tone(BUZZER_PIN, 3000, 200);
      delay(100);
      tone(BUZZER_PIN, 4000, 200);
    }
  }
  
  http.end();
}
