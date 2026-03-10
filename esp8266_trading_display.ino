/*
  ESP8266 Trading Bot Display - PRODUCTION VERSION
  
  Hardware:
  - ESP8266 (NodeMCU/Wemos D1 Mini)
  - OLED 128x64 (SSD1306) - I2C
  - Button on D3 (GPIO0)
  - LED on D4 (GPIO2)
  
  Wiring:
  OLED:
    GND → G
    VCC → 3V3
    SCL → D1 (GPIO5)
    SDA → D2 (GPIO4)
  
  BUTTON:
    D3 (GPIO0) → Button → GND
  
  LED:
    D4 (GPIO2) → 220Ω Resistor → LED+ → LED- → GND
    
  Features:
  - Real-time P&L display
  - Open positions monitoring
  - New trade alerts with buzzer/LED
  - Multiple display modes (button cycle)
  - WiFi status indicator
*/

#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>
#include <WiFiClient.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

// ============ USER CONFIGURATION ============
const char* ssid = "YOUR_WIFI_SSID";           // ← CHANGE THIS
const char* password = "YOUR_WIFI_PASSWORD";    // ← CHANGE THIS
const char* serverUrl = "http://192.168.1.100:8000";  // ← CHANGE TO YOUR SERVER IP

// Pins (Use GPIO numbers for maximum compatibility)
#define BUTTON_PIN 0     // GPIO0 = D3 on NodeMCU, FLASH button
#define LED_PIN 2        // GPIO2 = D4 on NodeMCU, built-in LED
#define BUZZER_PIN 14    // GPIO14 = D5 on NodeMCU

// I2C Pins for OLED
#define SDA_PIN 4        // GPIO4 = D2 on NodeMCU
#define SCL_PIN 5        // GPIO5 = D1 on NodeMCU

// OLED Display
#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
#define OLED_RESET -1
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

// ============ GLOBAL STATE ============
struct TradingData {
  bool systemEnabled;
  bool marketOpen;
  bool paperTrading;
  float todayPnl;
  int openPositions;
  int todayTrades;
  int maxTrades;
  bool wifiConnected;
  
  // Alert
  bool newAlert;
  String alertSymbol;
  float alertPrice;
  String alertTime;
};

TradingData data = {false, false, true, 0, 0, 0, 10, false, false, "", 0, ""};

// Position data (store up to 5)
#define MAX_POSITIONS 5
struct Position {
  String symbol;
  int qty;
  float entry;
  float ltp;
  float sl;
  float tp;
  float pnl;
  float pnlPct;
};
Position positions[MAX_POSITIONS];
int positionCount = 0;
int currentPositionIndex = 0;

// Display modes
enum DisplayMode {
  MODE_DASHBOARD,      // Main P&L display
  MODE_POSITIONS,      // List positions
  MODE_POSITION_DETAIL,// Individual position
  MODE_STATUS,         // System status
  MODE_ALERT,          // New trade alert
  MODE_COUNT
};
DisplayMode currentMode = MODE_DASHBOARD;

// Timing
unsigned long lastUpdate = 0;
unsigned long lastAlertCheck = 0;
unsigned long lastButtonPress = 0;
unsigned long alertDisplayStart = 0;
const unsigned long UPDATE_INTERVAL = 3000;      // 3 seconds
const unsigned long ALERT_CHECK_INTERVAL = 1000; // 1 second
const unsigned long DEBOUNCE_DELAY = 300;
const unsigned long ALERT_DISPLAY_TIME = 10000;  // 10 seconds

// LED patterns
enum LedPattern {
  LED_OFF,
  LED_ON,
  LED_BLINK_SLOW,
  LED_BLINK_FAST,
  LED_TRIPLE_BLINK
};
LedPattern ledPattern = LED_OFF;
unsigned long ledLastChange = 0;
bool ledState = false;
int ledBlinkCount = 0;

// Alert flag
bool showingAlert = false;

// ============ SETUP ============
void setup() {
  Serial.begin(115200);
  delay(100);
  
  Serial.println("\n╔════════════════════════════════════╗");
  Serial.println("║     MELON TRADING BOT DISPLAY      ║");
  Serial.println("║         Hardware Terminal          ║");
  Serial.println("╚════════════════════════════════════╝");
  
  // Initialize pins
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  pinMode(LED_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);
  digitalWrite(BUZZER_PIN, LOW);
  
  // Initialize OLED
  Wire.begin(SDA_PIN, SCL_PIN);  // SDA, SCL
  if(!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    Serial.println("SSD1306 allocation failed");
    // Blink LED rapidly to indicate error
    while(1) {
      digitalWrite(LED_PIN, HIGH);
      delay(100);
      digitalWrite(LED_PIN, LOW);
      delay(100);
    }
  }
  
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  
  // Show boot screen
  showBootScreen();
  
  // Connect WiFi
  connectWiFi();
  
  // Initial data fetch
  fetchTradingData();
  
  Serial.println("✓ Setup complete - Ready for trading!");
}

// ============ MAIN LOOP ============
void loop() {
  // Handle button press
  handleButton();
  
  // Update LED state
  updateLED();
  
  // Check for alerts (high priority)
  if (millis() - lastAlertCheck > ALERT_CHECK_INTERVAL) {
    checkForAlerts();
    lastAlertCheck = millis();
  }
  
  // Fetch trading data
  if (millis() - lastUpdate > UPDATE_INTERVAL) {
    fetchTradingData();
    fetchPositions();
    lastUpdate = millis();
  }
  
  // Return from alert mode after timeout
  if (showingAlert && millis() - alertDisplayStart > ALERT_DISPLAY_TIME) {
    showingAlert = false;
    currentMode = MODE_DASHBOARD;
    Serial.println("Alert display timeout - returning to dashboard");
  }
  
  // Update display
  updateDisplay();
  
  delay(50);
}

// ============ WIFI ============
void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);
  
  display.clearDisplay();
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.println("Connecting to WiFi...");
  display.print("SSID: ");
  display.println(ssid);
  display.display();
  
  Serial.print("Connecting to WiFi");
  
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 40) {
    delay(250);
    Serial.print(".");
    
    // Animate on display
    display.print(".");
    if (attempts % 20 == 19) {
      display.setCursor(0, 24);
    }
    display.display();
    
    // Blink LED while connecting
    digitalWrite(LED_PIN, (attempts / 2) % 2);
    attempts++;
  }
  
  data.wifiConnected = (WiFi.status() == WL_CONNECTED);
  
  if (data.wifiConnected) {
    Serial.println("\n✓ WiFi Connected!");
    Serial.print("  IP: ");
    Serial.println(WiFi.localIP());
    Serial.print("  RSSI: ");
    Serial.print(WiFi.RSSI());
    Serial.println(" dBm");
    
    display.clearDisplay();
    display.setCursor(0, 0);
    display.println("✓ WiFi Connected!");
    display.println();
    display.print("IP:\n");
    display.println(WiFi.localIP());
    display.println();
    display.print("Signal: ");
    display.print(WiFi.RSSI());
    display.println(" dBm");
    display.display();
    
    // Success flash
    for (int i = 0; i < 3; i++) {
      digitalWrite(LED_PIN, HIGH);
      delay(100);
      digitalWrite(LED_PIN, LOW);
      delay(100);
    }
  } else {
    Serial.println("\n✗ WiFi Connection Failed!");
    
    display.clearDisplay();
    display.setCursor(0, 0);
    display.println("✗ WiFi Failed!");
    display.println();
    display.println("Check:");
    display.println("- SSID/Password");
    display.println("- Router");
    display.display();
    
    // Error blink
    setLedPattern(LED_BLINK_FAST);
  }
  
  delay(1500);
}

// ============ BUTTON ============
void handleButton() {
  if (digitalRead(BUTTON_PIN) == LOW) {
    if (millis() - lastButtonPress > DEBOUNCE_DELAY) {
      lastButtonPress = millis();
      
      // Exit alert mode if showing
      if (showingAlert) {
        showingAlert = false;
        currentMode = MODE_DASHBOARD;
        Serial.println("Button: Dismissed alert");
        return;
      }
      
      // In positions mode, cycle through positions
      if (currentMode == MODE_POSITION_DETAIL && positionCount > 0) {
        currentPositionIndex = (currentPositionIndex + 1) % positionCount;
        Serial.print("Button: Position ");
        Serial.println(currentPositionIndex + 1);
      } else {
        // Cycle through main modes
        currentMode = (DisplayMode)((currentMode + 1) % MODE_COUNT);
        // Skip alert mode (it's automatic) and position detail if no positions
        if (currentMode == MODE_ALERT) currentMode = MODE_DASHBOARD;
        if (currentMode == MODE_POSITION_DETAIL && positionCount == 0) {
          currentMode = MODE_STATUS;
        }
        
        Serial.print("Button: Mode ");
        Serial.println(currentMode);
      }
      
      // Button feedback
      digitalWrite(LED_PIN, HIGH);
      delay(50);
      digitalWrite(LED_PIN, LOW);
    }
  }
}

// ============ LED CONTROL ============
void setLedPattern(LedPattern pattern) {
  ledPattern = pattern;
  ledLastChange = millis();
  ledBlinkCount = 0;
}

void updateLED() {
  unsigned long now = millis();
  
  switch (ledPattern) {
    case LED_OFF:
      digitalWrite(LED_PIN, LOW);
      break;
      
    case LED_ON:
      digitalWrite(LED_PIN, HIGH);
      break;
      
    case LED_BLINK_SLOW:
      if (now - ledLastChange > 1000) {
        ledLastChange = now;
        ledState = !ledState;
        digitalWrite(LED_PIN, ledState);
      }
      break;
      
    case LED_BLINK_FAST:
      if (now - ledLastChange > 200) {
        ledLastChange = now;
        ledState = !ledState;
        digitalWrite(LED_PIN, ledState);
      }
      break;
      
    case LED_TRIPLE_BLINK:
      if (now - ledLastChange > 150) {
        ledLastChange = now;
        ledBlinkCount++;
        if (ledBlinkCount <= 6) {
          digitalWrite(LED_PIN, ledBlinkCount % 2);
        } else {
          setLedPattern(LED_ON);  // Stay on after triple blink
        }
      }
      break;
  }
}

// ============ API CALLS ============
void fetchTradingData() {
  if (WiFi.status() != WL_CONNECTED) {
    data.wifiConnected = false;
    setLedPattern(LED_BLINK_FAST);
    return;
  }
  
  data.wifiConnected = true;
  
  WiFiClient client;
  HTTPClient http;
  
  String url = String(serverUrl) + "/api/esp/stats";
  http.begin(client, url);
  http.setTimeout(3000);
  
  int httpCode = http.GET();
  
  if (httpCode == 200) {
    String payload = http.getString();
    
    StaticJsonDocument<512> doc;
    DeserializationError error = deserializeJson(doc, payload);
    
    if (!error) {
      data.systemEnabled = doc["system_enabled"] | false;
      data.marketOpen = doc["market_open"] | false;
      data.paperTrading = doc["paper_trading"] | true;
      data.todayPnl = doc["today_pnl"] | 0.0;
      data.openPositions = doc["open_positions"] | 0;
      data.todayTrades = doc["today_trades"] | 0;
      data.maxTrades = doc["max_trades"] | 10;
      
      // Update LED based on status
      updateStatusLED();
      
    } else {
      Serial.print("JSON parse error: ");
      Serial.println(error.c_str());
    }
  } else {
    Serial.print("HTTP error: ");
    Serial.println(httpCode);
  }
  
  http.end();
}

void fetchPositions() {
  if (WiFi.status() != WL_CONNECTED) return;
  
  WiFiClient client;
  HTTPClient http;
  
  String url = String(serverUrl) + "/api/esp/positions";
  http.begin(client, url);
  http.setTimeout(3000);
  
  int httpCode = http.GET();
  
  if (httpCode == 200) {
    String payload = http.getString();
    
    StaticJsonDocument<2048> doc;
    DeserializationError error = deserializeJson(doc, payload);
    
    if (!error) {
      JsonArray arr = doc["positions"].as<JsonArray>();
      positionCount = min((int)arr.size(), MAX_POSITIONS);
      
      int i = 0;
      for (JsonObject pos : arr) {
        if (i >= MAX_POSITIONS) break;
        positions[i].symbol = pos["symbol"] | "";
        positions[i].qty = pos["qty"] | 0;
        positions[i].entry = pos["entry"] | 0.0;
        positions[i].ltp = pos["ltp"] | 0.0;
        positions[i].sl = pos["sl"] | 0.0;
        positions[i].tp = pos["tp"] | 0.0;
        positions[i].pnl = pos["pnl"] | 0.0;
        positions[i].pnlPct = pos["pnl_pct"] | 0.0;
        i++;
      }
    }
  }
  
  http.end();
}

void checkForAlerts() {
  if (WiFi.status() != WL_CONNECTED) return;
  
  WiFiClient client;
  HTTPClient http;
  
  String url = String(serverUrl) + "/api/esp/alert";
  http.begin(client, url);
  http.setTimeout(2000);
  
  int httpCode = http.GET();
  
  if (httpCode == 200) {
    String payload = http.getString();
    
    StaticJsonDocument<256> doc;
    DeserializationError error = deserializeJson(doc, payload);
    
    if (!error && doc["new_alert"] == true) {
      // New alert received!
      data.newAlert = true;
      data.alertSymbol = doc["symbol"] | "";
      data.alertPrice = doc["price"] | 0.0;
      data.alertTime = doc["time"] | "";
      
      showingAlert = true;
      alertDisplayStart = millis();
      currentMode = MODE_ALERT;
      
      // Visual and audio notification
      setLedPattern(LED_TRIPLE_BLINK);
      digitalWrite(BUZZER_PIN, HIGH);
      delay(200);
      digitalWrite(BUZZER_PIN, LOW);
      
      Serial.println("🚨 NEW TRADE ALERT!");
      Serial.print("   Symbol: ");
      Serial.println(data.alertSymbol);
      Serial.print("   Price: ₹");
      Serial.println(data.alertPrice);
    }
  }
  
  http.end();
}

void updateStatusLED() {
  if (!data.systemEnabled) {
    setLedPattern(LED_OFF);
  } else if (!data.marketOpen) {
    setLedPattern(LED_BLINK_SLOW);
  } else if (data.todayPnl < -1000) {
    setLedPattern(LED_BLINK_FAST);
  } else if (data.todayPnl > 0) {
    setLedPattern(LED_ON);
  } else {
    setLedPattern(LED_BLINK_SLOW);
  }
}

// ============ DISPLAY SCREENS ============
void updateDisplay() {
  if (showingAlert) {
    showAlert();
    return;
  }
  
  switch (currentMode) {
    case MODE_DASHBOARD:
      showDashboard();
      break;
    case MODE_POSITIONS:
      showPositionsList();
      break;
    case MODE_POSITION_DETAIL:
      showPositionDetail();
      break;
    case MODE_STATUS:
      showStatus();
      break;
    default:
      showDashboard();
  }
}

void showBootScreen() {
  display.clearDisplay();
  
  // Logo
  display.setTextSize(1);
  display.setCursor(20, 0);
  display.println("ME LON BOT");
  display.drawLine(20, 9, 108, 9, SSD1306_WHITE);
  
  // Title
  display.setTextSize(2);
  display.setCursor(10, 16);
  display.println("TRADING");
  display.setCursor(10, 34);
  display.println("TERMINAL");
  
  // Hardware info
  display.setTextSize(1);
  display.setCursor(0, 54);
  display.print("OLED+BTN+LED Ready");
  
  display.display();
  delay(2000);
}

void showDashboard() {
  display.clearDisplay();
  
  // Header with mode indicator
  display.setTextSize(1);
  display.setCursor(0, 0);
  if (data.paperTrading) {
    display.print("[PAPER]");
  } else {
    display.print("[LIVE]");
  }
  display.setCursor(100, 0);
  display.print("DASH");
  
  // Divider
  display.drawLine(0, 10, 128, 10, SSD1306_WHITE);
  
  // Large P&L display
  display.setTextSize(2);
  display.setCursor(0, 14);
  if (data.todayPnl >= 0) {
    display.print("+₹");
  } else {
    display.print("-₹");
  }
  display.print(abs((int)data.todayPnl));
  
  // P&L Label
  display.setTextSize(1);
  display.setCursor(0, 32);
  if (data.todayPnl >= 0) {
    display.print("PROFIT TODAY");
  } else {
    display.print("LOSS TODAY");
  }
  
  // Stats
  display.drawLine(0, 42, 128, 42, SSD1306_WHITE);
  
  display.setCursor(0, 46);
  display.print("POS:");
  display.print(data.openPositions);
  
  display.setCursor(45, 46);
  display.print("TRD:");
  display.print(data.todayTrades);
  display.print("/");
  display.print(data.maxTrades);
  
  // Status line
  display.setCursor(0, 56);
  if (!data.systemEnabled) {
    display.print("⚠ TRADING OFF");
  } else if (!data.marketOpen) {
    display.print("⏸ MARKET CLOSED");
  } else {
    display.print("✓ ACTIVE");
  }
  
  display.display();
}

void showPositionsList() {
  display.clearDisplay();
  
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.print("POSITIONS (");
  display.print(positionCount);
  display.print(")");
  display.setCursor(100, 0);
  display.print("LIST");
  
  display.drawLine(0, 10, 128, 10, SSD1306_WHITE);
  
  if (positionCount == 0) {
    display.setCursor(0, 25);
    display.print("No open positions");
    display.setCursor(0, 38);
    display.print("Waiting signals...");
  } else {
    // Show first 3 positions
    for (int i = 0; i < min(positionCount, 3); i++) {
      int y = 14 + (i * 16);
      display.setCursor(0, y);
      display.print(positions[i].symbol);
      
      display.setCursor(50, y);
      display.print("₹");
      display.print((int)positions[i].pnl);
      
      display.setCursor(90, y);
      if (positions[i].pnlPct >= 0) {
        display.print("+");
      }
      display.print(positions[i].pnlPct, 1);
      display.print("%");
    }
  }
  
  display.drawLine(0, 58, 128, 58, SSD1306_WHITE);
  display.setCursor(0, 60);
  display.print("Btn: detail  Hold: dash");
  
  display.display();
}

void showPositionDetail() {
  if (positionCount == 0) {
    currentMode = MODE_DASHBOARD;
    return;
  }
  
  Position &p = positions[currentPositionIndex];
  
  display.clearDisplay();
  
  // Header
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.print(p.symbol);
  display.setCursor(90, 0);
  display.print("");
  display.print(currentPositionIndex + 1);
  display.print("/");
  display.print(positionCount);
  
  display.drawLine(0, 10, 128, 10, SSD1306_WHITE);
  
  // P&L Large
  display.setTextSize(2);
  display.setCursor(0, 14);
  if (p.pnl >= 0) display.print("+");
  display.print("₹");
  display.print((int)p.pnl);
  
  // Details
  display.setTextSize(1);
  
  display.setCursor(0, 34);
  display.print("Qty: ");
  display.print(p.qty);
  display.print(" @ ₹");
  display.print(p.entry, 1);
  
  display.setCursor(0, 44);
  display.print("LTP: ₹");
  display.print(p.ltp, 1);
  display.print("  ");
  if (p.pnlPct >= 0) display.print("+");
  display.print(p.pnlPct, 1);
  display.print("%");
  
  display.setCursor(0, 54);
  display.print("SL:₹");
  display.print(p.sl, 0);
  display.print(" TP:₹");
  display.print(p.tp, 0);
  
  display.display();
}

void showStatus() {
  display.clearDisplay();
  
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.print("SYSTEM STATUS");
  display.setCursor(100, 0);
  display.print("INFO");
  
  display.drawLine(0, 10, 128, 10, SSD1306_WHITE);
  
  display.setCursor(0, 14);
  display.print("WiFi: ");
  if (data.wifiConnected) {
    display.print("✓ Connected");
    display.setCursor(0, 24);
    display.print("RSSI: ");
    display.print(WiFi.RSSI());
    display.print(" dBm");
  } else {
    display.print("✗ Disconnected");
  }
  
  display.setCursor(0, 38);
  display.print("Server: ");
  // Truncate server URL to fit
  String srv = String(serverUrl);
  srv.replace("http://", "");
  display.print(srv.substring(0, 16));
  
  display.setCursor(0, 50);
  display.print("Mode: ");
  display.print(data.paperTrading ? "PAPER" : "LIVE");
  
  display.display();
}

void showAlert() {
  display.clearDisplay();
  
  // Flashing border effect
  bool flash = (millis() / 500) % 2;
  if (flash) {
    display.drawRect(0, 0, 128, 64, SSD1306_WHITE);
  }
  
  // Alert header
  display.setTextSize(1);
  display.setCursor(30, 4);
  display.print("⚠ NEW ALERT!");
  
  // Symbol (Large)
  display.setTextSize(2);
  display.setCursor(25, 18);
  display.print(data.alertSymbol);
  
  // Price
  display.setTextSize(1);
  display.setCursor(30, 38);
  display.print("Price: ₹");
  display.print(data.alertPrice, 2);
  
  // Time
  display.setCursor(35, 48);
  display.print("Time: ");
  display.print(data.alertTime);
  
  // Footer
  display.setCursor(10, 58);
  display.print("Btn: dismiss alert");
  
  display.display();
}
