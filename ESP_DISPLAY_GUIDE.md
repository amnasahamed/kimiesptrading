# ESP Trading Display Guide v2.0

## Overview

Enhanced ESP32 and ESP8266 firmware for the Trading Bot with full support for:
- **Paper + Live Trading** display
- **Strategy Optimizer** insights
- **AI Recommendations**
- **Better alerts**
- **Strategy configuration view**

## Hardware Requirements

### ESP32 Version
- **Board:** ESP32-WROOM-32 (DevKit V1)
- **Display:** 1.3" 128x64 OLED (SSD1306 I2C)
- **Pins:**
  - OLED SDA: GPIO21
  - OLED SCL: GPIO22
  - Button: GPIO4
  - Buzzer: GPIO18
  - LED: GPIO2 (built-in)

### ESP8266 Version
- **Board:** NodeMCU or Wemos D1 Mini
- **Display:** 1.3" 128x64 OLED (SSD1306 I2C)
- **Pins:**
  - OLED SDA: D2 (GPIO4)
  - OLED SCL: D1 (GPIO5)
  - Button: D6 (GPIO12)
  - Buzzer: D5 (GPIO14)
  - LED: D4 (GPIO2, built-in)

## Installation

### 1. Install Libraries

**Required Libraries (Arduino IDE):**
- `WiFi` (built-in for ESP32) / `ESP8266WiFi` (ESP8266)
- `HTTPClient` / `ESP8266HTTPClient`
- `ArduinoJson` by Benoit Blanchon (v6.x)
- `Adafruit SSD1306`
- `Adafruit GFX`

**Install via Library Manager:**
```
Sketch → Include Library → Manage Libraries
Search: "ArduinoJson", "Adafruit SSD1306"
```

### 2. Configure WiFi

Edit the code before uploading:

```cpp
const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASS = "YOUR_WIFI_PASSWORD";
const char* SERVER_URL = "http://192.168.1.100:8000";  // Your bot's IP
```

### 3. Upload Code

**ESP32:**
- Board: "ESP32 Dev Module"
- Upload Speed: 921600
- Flash Mode: QIO
- Flash Size: 4MB

**ESP8266:**
- Board: "NodeMCU 1.0 (ESP-12E)"
- Upload Speed: 921600
- Flash Size: 4MB (FS:2MB OTA:~1019KB)

## Features

### Screen 1: Overview
```
[PAPER MODE]  OPEN
────────────────
Paper: +₹1,250 (5)
Live:  -₹300  (2)
Total: +₹950

Positions: 3
System: ACTIVE          1/5
```

Shows:
- Trading mode (Paper/Live)
- Market status (Open/Closed)
- Separate Paper and Live P&L
- Trade counts per mode
- Total combined P&L
- Open positions count
- System status

### Screen 2: Positions
```
POSITIONS (3)         2/5
────────────────
RELIANCE L  +450 +2.5%
TCS       P  -120 -1.2%
INFY      L  +890 +3.1%
```

Shows:
- Symbol name
- Mode indicator (P=Paper, L=Live)
- P&L in rupees
- P&L percentage

**ESP32:** Shows up to 4 positions
**ESP8266:** Shows up to 4 positions (memory optimized)

### Screen 3: AI Insights
```
AI RECOMMENDATIONS    3/5
────────────────
[!] Best Hour: 10:00
10:00 shows 73% win 
rate with ₹1,250 avg
+2 more in app
```

Shows:
- Top AI recommendation
- Priority indicator ([!] high, [?] medium, [i] low)
- Truncated message
- Count of additional recommendations

### Screen 4: Strategy Config
```
STRATEGY CONFIG       4/5
────────────────
Risk: 1.0%
Min R:R: 1:2
SL ATR: 1.5x
TP ATR: 3.0x
```

Shows:
- Risk percentage per trade
- Minimum Risk:Reward ratio
- ATR multipliers for SL/TP
- (ESP8266 only) System + WiFi status

### Screen 5: Network (ESP32 only)
```
NETWORK STATUS        5/5
────────────────
WiFi: OK
IP: 192.168.1.45
RSSI: -52 dBm
Server: OK
```

Shows:
- WiFi connection status
- IP address
- Signal strength (RSSI)
- Server connectivity

## Alert System

When a new trade is received:
1. Screen flashes (inverse video)
2. Buzzer plays melody
3. Shows symbol and price
4. Auto-clears after 5 seconds

```
████████████████
██  NEW TRADE  ██
██            ██
██  RELIANCE  ██
██  @ 2450.50 ██
████████████████
```

## Controls

**Button Functions:**
- **Short Press:** Next screen
- **Auto-cycle:** Changes screen every 8-10 seconds

**LED Indicators:**
- **Off:** Normal operation
- **Blink:** WiFi connecting
- **On (brief):** Button pressed

## API Endpoints Used

| Endpoint | Purpose | ESP32 | ESP8266 |
|----------|---------|-------|---------|
| `/api/esp/stats` | Basic stats | ✓ | ✓ |
| `/api/insights` | Recommendations | ✓ | ✓ |
| `/api/esp/positions` | Open positions | ✓ | ✓ |
| `/api/esp/alert` | New trade alerts | ✓ | ✓ |
| `/api/strategy/analytics` | Full analytics | ✓ | ✗ |

## Differences: ESP32 vs ESP8266

| Feature | ESP32 | ESP8266 |
|---------|-------|---------|
| Screens | 5 | 4 |
| Positions shown | 4 | 4 |
| Update rate | 5 seconds | 8 seconds |
| Display FPS | ~20fps | ~10fps |
| Network screen | Yes | No |
| Memory (free heap) | ~200KB | ~40KB |
| HTTP timeout | 5s | 5s |
| Alert sound | Full melody | Simple beep |

## Troubleshooting

### Display stays blank
1. Check I2C address: Try `0x3C` or `0x3D`
2. Verify wiring: SDA and SCL connected correctly
3. Check OLED is 1.3" (128x64), not 0.96" (128x32)

### WiFi won't connect
1. Verify SSID and password in code
2. Check 2.4GHz network (ESP doesn't support 5GHz)
3. Try moving closer to router
4. Check for special characters in WiFi password

### Shows "No positions" but bot has trades
1. Check `SERVER_URL` matches your bot's IP
2. Verify bot is running: `curl http://YOUR_IP:8000/health`
3. Check firewall isn't blocking port 8000

### Alert not showing
1. Verify `/api/esp/alert` endpoint returns data
2. Check buzzer is connected to correct pin
3. Alert shows for 5 seconds then auto-clears

### Slow refresh / crashes (ESP8266)
1. Normal - ESP8266 has limited memory
2. Reduce update frequency (change `DATA_INTERVAL`)
3. Restart device to free memory

## Customization

### Change Update Interval
```cpp
// ESP32 - default 5 seconds
#define DATA_INTERVAL 10000  // 10 seconds

// ESP8266 - default 8 seconds
#define DATA_INTERVAL 15000  // 15 seconds
```

### Disable Auto-Cycle
```cpp
// In main loop, comment out:
// if (now - lastScreenCycle >= AUTO_CYCLE_TIME) {
//     nextScreen();
//     lastScreenCycle = now;
// }
```

### Change Alert Sound
```cpp
// Simple beep
void playAlertSound() {
    tone(PIN_BUZZER, 2000, 500);  // 2kHz for 500ms
}

// Morse code "SOS"
void playAlertSound() {
    // S (...)
    for(int i=0; i<3; i++) { tone(PIN_BUZZER, 2000, 100); delay(100); }
    delay(200);
    // O (---)
    for(int i=0; i<3; i++) { tone(PIN_BUZZER, 2000, 300); delay(100); }
    delay(200);
    // S (...)
    for(int i=0; i<3; i++) { tone(PIN_BUZZER, 2000, 100); delay(100); }
}
```

### Add Custom Screen

Add to `enum Screen`:
```cpp
enum Screen {
    SCR_OVERVIEW,
    SCR_POSITIONS,
    SCR_INSIGHTS,
    SCR_STRATEGY,
    SCR_NETWORK,
    SCR_CUSTOM,  // Add this
    SCR_COUNT
};
```

Add display function:
```cpp
void showCustomScreen() {
    display.clearDisplay();
    display.setCursor(0, 0);
    display.print("CUSTOM DATA");
    // Your custom display code
    display.display();
}
```

Update switch in `updateDisplay()`:
```cpp
case SCR_CUSTOM:
    showCustomScreen();
    break;
```

## Power Saving Tips

### For Battery Operation

1. **Reduce update frequency:**
```cpp
#define DATA_INTERVAL 30000  // 30 seconds
```

2. **Disable auto-cycle:**
```cpp
#define AUTO_CYCLE_TIME 60000  // 1 minute
```

3. **Use ESP8266 Light Sleep** (add to loop):
```cpp
// After display update
if (WiFi.status() == WL_CONNECTED) {
    WiFi.setSleepMode(WIFI_LIGHT_SLEEP);
}
```

4. **Dim display** (add after init):
```cpp
display.ssd1306_command(SSD1306_SETCONTRAST);
display.ssd1306_command(50);  // Lower = dimmer (0-255)
```

## Serial Monitor Output

Connect at **115200 baud** to see:
```
================================
ESP32 Trading Display v2.0
================================

Connecting WiFi...
WiFi Connected!
IP: 192.168.1.45

Setup complete!
Fetching data...
Positions: 3
Paper P&L: 1250
Live P&L: -300
Recommendations: 2
```

## Files

| File | Board | Lines | Features |
|------|-------|-------|----------|
| `esp32_trading_display_v2.ino` | ESP32 | 843 | Full features, 5 screens |
| `esp8266_trading_display_v2.ino` | ESP8266 | 641 | Optimized, 4 screens |

## Support

**WiFi Connection Issues:**
- Use 2.4GHz network
- Check signal strength (>-70 dBm ideal)
- Verify no MAC filtering on router

**Display Issues:**
- Try I2C scanner to find address
- Check wiring (SDA/SCL not swapped)
- Verify 3.3V power supply

**API Connection Issues:**
- Test: `curl http://YOUR_IP:8000/api/esp/stats`
- Check firewall rules
- Verify bot is running and accessible

---

**Happy Trading! 📈**
