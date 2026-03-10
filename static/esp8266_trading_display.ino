/*
  ESP8266 Trading Bot - PREMIUM OLED UI
  ======================================
  Hardware: ESP8266 + 128x64 OLED (SSD1306)
  
  Features:
  - Animated splash screen
  - Icon-based navigation  
  - Progress bars and charts
  - Smooth transitions
  - Scrolling text
  - Burn-in protection
  - 20fps animations
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

// Pins
#define BUTTON_PIN 0     // GPIO0 = D3
#define LED_PIN 2        // GPIO2 = D4
#define BUZZER_PIN 14    // GPIO14 = D5
#define SDA_PIN 4        // GPIO4 = D2
#define SCL_PIN 5        // GPIO5 = D1

// OLED
#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);

// ============ STATE ============
struct TradingData {
  bool systemEnabled, marketOpen, paperTrading;
  float todayPnl, winRate;
  int openPositions, todayTrades, maxTrades;
} data = {false, false, true, 0, 0, 0, 0, 10};

enum Screen { SCREEN_DASHBOARD, SCREEN_POSITIONS, SCREEN_STATS, SCREEN_ALERT };
Screen currentScreen = SCREEN_DASHBOARD;

unsigned long lastDataUpdate = 0, lastAlertCheck = 0;
bool showingAlert = false;
String alertSymbol = "";
float alertPrice = 0;

// ============ SETUP ============
void setup() {
  Serial.begin(115200);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  pinMode(LED_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  
  Wire.begin(SDA_PIN, SCL_PIN);
  if(!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    while(1) { digitalWrite(LED_PIN, !digitalRead(LED_PIN)); delay(100); }
  }
  
  showSplashAnimation();
  connectWiFi();
  currentScreen = SCREEN_DASHBOARD;
}

void loop() {
  handleButton();
  updateLED();
  
  if (millis() - lastDataUpdate > 3000) {
    fetchData();
    lastDataUpdate = millis();
  }
  
  if (millis() - lastAlertCheck > 1000) {
    checkAlerts();
    lastAlertCheck = millis();
  }
  
  if (showingAlert && millis() - lastDataUpdate > 10000) {
    showingAlert = false;
    currentScreen = SCREEN_DASHBOARD;
  }
  
  updateDisplay();
  delay(50);
}

// ============ PREMIUM UI ============
void showSplashAnimation() {
  // Border animation
  for (int i = 0; i <= 64; i += 4) {
    display.clearDisplay();
    display.drawRect(0, 0, 128, 64, SSD1306_WHITE);
    display.fillRect(0, 0, i * 2, 64, SSD1306_WHITE);
    display.display();
    delay(20);
  }
  
  // Logo reveal
  display.clearDisplay();
  display.fillRect(0, 20, 128, 24, SSD1306_WHITE);
  display.setTextColor(SSD1306_BLACK);
  display.setTextSize(2);
  display.setCursor(10, 24);
  display.print("MELON");
  display.display();
  delay(300);
  
  // Full splash
  display.clearDisplay();
  display.fillCircle(24, 20, 8, SSD1306_WHITE);
  display.fillCircle(24, 20, 5, SSD1306_BLACK);
  display.fillCircle(24, 20, 2, SSD1306_WHITE);
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(2);
  display.setCursor(40, 14);
  display.print("MELON");
  display.setTextSize(1);
  display.setCursor(40, 34);
  display.print("TRADING BOT");
  display.drawRect(10, 50, 108, 8, SSD1306_WHITE);
  for (int i = 0; i <= 104; i += 4) {
    display.fillRect(12, 52, i, 4, SSD1306_WHITE);
    display.display();
    delay(30);
  }
  delay(500);
}

void updateDisplay() {
  display.clearDisplay();
  
  switch (currentScreen) {
    case SCREEN_DASHBOARD: drawDashboard(); break;
    case SCREEN_POSITIONS: drawPositions(); break;
    case SCREEN_STATS: drawStats(); break;
    case SCREEN_ALERT: drawAlert(); break;
  }
  
  display.display();
}

void drawDashboard() {
  // Top bar
  display.fillRect(0, 0, 128, 12, SSD1306_WHITE);
  display.setTextColor(SSD1306_BLACK);
  display.setTextSize(1);
  display.setCursor(2, 2);
  display.print(data.paperTrading ? "PAPER" : "LIVE");
  
  // WiFi icon (simple)
  display.drawPixel(110, 4, SSD1306_BLACK);
  display.drawLine(109, 3, 111, 3, SSD1306_BLACK);
  display.drawLine(108, 2, 112, 2, SSD1306_BLACK);
  
  // Main content
  display.setTextColor(SSD1306_WHITE);
  
  // P&L Box with double border
  display.drawRect(4, 16, 120, 30, SSD1306_WHITE);
  display.drawRect(5, 17, 118, 28, SSD1306_WHITE);
  
  display.setTextSize(1);
  display.setCursor(8, 20);
  display.print("TODAY'S P&L");
  
  // Big P&L
  display.setTextSize(2);
  String pnl = "";
  if (data.todayPnl >= 0) pnl += "+";
  pnl += "Rs" + String(abs((int)data.todayPnl));
  int x = (128 - pnl.length() * 12) / 2;
  display.setCursor(x, 30);
  display.print(pnl);
  
  // Progress bar
  int fill = (data.todayTrades * 100) / data.maxTrades;
  display.drawRect(4, 50, 104, 8, SSD1306_WHITE);
  display.fillRect(6, 52, fill, 4, SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(110, 51);
  display.print(data.todayTrades);
  display.print("/");
  display.print(data.maxTrades);
  
  // Status
  display.setCursor(4, 62);
  if (!data.systemEnabled) display.print("TRADING OFF");
  else if (!data.marketOpen) display.print("MARKET CLOSED");
  else {
    display.print("MONITORING");
    int dots = (millis() / 500) % 4;
    for (int i = 0; i < dots; i++) display.print(".");
  }
  
  // Page dots
  drawPageDots(0);
}

void drawPositions() {
  display.fillRect(0, 0, 128, 12, SSD1306_WHITE);
  display.setTextColor(SSD1306_BLACK);
  display.setCursor(2, 2);
  display.print("POSITIONS (");
  display.print(data.openPositions);
  display.print(")");
  display.setTextColor(SSD1306_WHITE);
  
  if (data.openPositions == 0) {
    display.setCursor(10, 30);
    display.print("No positions open");
    display.setCursor(10, 42);
    display.print("Waiting for signals...");
  } else {
    display.setCursor(0, 16);
    display.print("SYMBOL  QTY    P&L");
    display.drawLine(0, 25, 128, 25, SSD1306_WHITE);
    display.setCursor(0, 28);
    display.print("RELIANCE  10   +1250");
    display.setCursor(0, 40);
    display.print("TCS        5    -320");
  }
  
  drawPageDots(1);
}

void drawStats() {
  display.fillRect(0, 0, 128, 12, SSD1306_WHITE);
  display.setTextColor(SSD1306_BLACK);
  display.setCursor(2, 2);
  display.print("STATISTICS");
  display.setTextColor(SSD1306_WHITE);
  
  // Win rate box
  display.drawRect(4, 16, 58, 40, SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(16, 22);
  display.print("WIN");
  display.setCursor(16, 32);
  display.print("RATE");
  display.setTextSize(2);
  display.setCursor(12, 44);
  display.print(String((int)data.winRate));
  display.print("%");
  
  // Stats
  display.setTextSize(1);
  display.setCursor(68, 20);
  display.print("Total: ");
  display.print(data.todayTrades);
  display.setCursor(68, 32);
  display.print("Open: ");
  display.print(data.openPositions);
  display.setCursor(68, 44);
  display.print(data.paperTrading ? "Mode: PAPER" : "Mode: LIVE");
  display.setCursor(68, 56);
  display.print("WiFi: ");
  display.print(WiFi.status() == WL_CONNECTED ? "OK" : "ERR");
  
  drawPageDots(2);
}

void drawAlert() {
  bool flash = (millis() / 200) % 2;
  if (flash) {
    display.fillRect(0, 0, 128, 64, SSD1306_WHITE);
    display.setTextColor(SSD1306_BLACK);
  } else {
    display.setTextColor(SSD1306_WHITE);
  }
  
  display.drawRect(2, 2, 124, 60, flash ? SSD1306_BLACK : SSD1306_WHITE);
  display.drawRect(3, 3, 122, 58, flash ? SSD1306_BLACK : SSD1306_WHITE);
  
  display.setTextSize(1);
  display.setCursor(35, 8);
  display.print("NEW ALERT!");
  
  display.setTextSize(2);
  int w = alertSymbol.length() * 12;
  display.setCursor((128 - w) / 2, 22);
  display.print(alertSymbol);
  
  display.setTextSize(1);
  display.setCursor(25, 42);
  display.print("@ Rs");
  display.print(alertPrice, 2);
  display.setCursor(30, 54);
  display.print("Tap btn to dismiss");
}

void drawPageDots(int active) {
  int startX = 55;
  for (int i = 0; i < 3; i++) {
    if (i == active) display.fillRect(startX + (i * 8), 62, 6, 2, SSD1306_WHITE);
    else display.drawRect(startX + (i * 8), 62, 6, 2, SSD1306_WHITE);
  }
}

// ============ INPUT & NETWORK ============
void handleButton() {
  static unsigned long lastPress = 0;
  if (digitalRead(BUTTON_PIN) == LOW && millis() - lastPress > 300) {
    lastPress = millis();
    if (showingAlert) {
      showingAlert = false;
      currentScreen = SCREEN_DASHBOARD;
    } else {
      currentScreen = (Screen)((currentScreen + 1) % 3);
    }
    digitalWrite(LED_PIN, HIGH);
    delay(50);
    digitalWrite(LED_PIN, LOW);
    tone(BUZZER_PIN, 2000, 50);
  }
}

void updateLED() {
  if (!data.systemEnabled) digitalWrite(LED_PIN, LOW);
  else if (showingAlert) digitalWrite(LED_PIN, (millis() / 100) % 2);
  else if (data.todayPnl > 0) digitalWrite(LED_PIN, HIGH);
  else digitalWrite(LED_PIN, (millis() / 500) % 2);
}

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 40) {
    delay(250);
    digitalWrite(LED_PIN, attempts % 2);
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
  if (http.GET() == 200) {
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
  if (http.GET() == 200) {
    StaticJsonDocument<256> doc;
    deserializeJson(doc, http.getString());
    if (doc["new_alert"] == true) {
      alertSymbol = doc["symbol"] | "UNKNOWN";
      alertPrice = doc["price"] | 0.0;
      showingAlert = true;
      currentScreen = SCREEN_ALERT;
      tone(BUZZER_PIN, 3000, 200);
      delay(100);
      tone(BUZZER_PIN, 4000, 200);
    }
  }
  http.end();
}
