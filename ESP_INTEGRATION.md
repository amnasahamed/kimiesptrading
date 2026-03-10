# ESP8266 Trading Display Integration

Transform your trading bot into a physical trading terminal with ESP8266 + OLED display.

## Hardware Requirements

- **ESP8266** (NodeMCU v3 or Wemos D1 Mini)
- **OLED Display** 0.96" 128x64 (SSD1306, I2C)
- **Push Button** (optional, can use FLASH button)
- **LED** + 220Ω resistor (optional, can use built-in LED)
- **Buzzer** (optional, for audio alerts)

## Wiring Diagram

### OLED Display (I2C)
```
OLED Pin    ESP8266 Pin
--------    -----------
GND    →    G (Ground)
VCC    →    3V3 (3.3V)
SCL    →    D1 (GPIO5)
SDA    →    D2 (GPIO4)
```

### Push Button
```
ESP8266 D3 (GPIO0) → Button → GND
```
*Note: The FLASH button on NodeMCU is connected to D3, so you can use that.*

### LED Indicator
```
ESP8266 D4 (GPIO2) → 220Ω Resistor → LED+ → LED- → GND
```
*Note: Built-in LED on most ESP8266 boards is already on D4.*

### Buzzer (Optional)
```
ESP8266 D5 (GPIO14) → Buzzer+ → Buzzer- → GND
```

## Software Setup

### 1. Install Arduino IDE
Download from: https://www.arduino.cc/en/software

### 2. Add ESP8266 Board Support
1. Open Arduino IDE → File → Preferences
2. Add to "Additional Board Manager URLs":
   ```
   http://arduino.esp8266.com/stable/package_esp8266com_index.json
   ```
3. Tools → Board → Boards Manager
4. Search "ESP8266" and install

### 3. Install Required Libraries
In Arduino IDE: Sketch → Include Library → Manage Libraries

Install these libraries:
- `ESP8266WiFi` (comes with ESP8266 board package)
- `ESP8266HTTPClient` (comes with ESP8266 board package)
- `ArduinoJson` by Benoit Blanchon (v6.x)
- `Adafruit SSD1306` by Adafruit
- `Adafruit GFX Library` by Adafruit

### 4. Configure the Code

Open `esp8266_trading_display.ino` and update:

```cpp
// ============ USER CONFIGURATION ============
const char* ssid = "YOUR_WIFI_SSID";           // ← Your WiFi name
const char* password = "YOUR_WIFI_PASSWORD";    // ← Your WiFi password
const char* serverUrl = "http://192.168.1.100:8000";  // ← Your server IP
```

**Find your server IP:**
```bash
# On your server, run:
ip addr show | grep "inet " | head -1

# Or for Raspberry Pi/Linux:
hostname -I
```

### 5. Upload Code
1. Connect ESP8266 to computer via USB
2. Arduino IDE → Tools → Board → Select your board (e.g., "NodeMCU 1.0")
3. Select correct COM port
4. Click Upload button

## Features

### Display Modes (Cycle with Button)

1. **DASHBOARD** - Shows today's P&L, open positions, trade count
2. **POSITIONS LIST** - List of all open positions with P&L
3. **POSITION DETAIL** - Detailed view of individual position (qty, entry, SL, TP)
4. **SYSTEM STATUS** - WiFi status, server connection, trading mode

### LED Indicators

| Pattern | Meaning |
|---------|---------|
| OFF | Trading disabled or error |
| Solid ON | Profit (positive P&L) |
| Slow Blink | Market closed, waiting |
| Fast Blink | Loss alert (< ₹-1000) or WiFi error |
| Triple Blink | New trade alert! |

### New Trade Alerts

When a Chartink webhook triggers:
1. LED flashes triple-blink pattern
2. Buzzer sounds (if connected)
3. Display switches to ALERT mode showing:
   - Symbol name
   - Entry price
   - Time of alert
4. Press button to dismiss alert

### Auto-Refresh

- Trading data updates every 3 seconds
- Alert check every 1 second
- Display updates continuously

## API Endpoints (for ESP)

The ESP uses these lightweight endpoints:

```
GET /api/esp/stats      - Compact trading stats
GET /api/esp/positions  - List of open positions
GET /api/esp/alert      - Check for new alerts
```

## Troubleshooting

### OLED Not Working
- Check I2C address: Run I2C scanner sketch
- Common addresses: 0x3C or 0x3D
- Check wiring: SDA→D2, SCL→D1

### WiFi Not Connecting
- Verify SSID and password
- Check 2.4GHz WiFi (ESP8266 doesn't support 5GHz)
- Move closer to router
- Check serial monitor for errors

### Server Connection Failed
- Verify server IP address
- Check server is running: `curl http://SERVER_IP:8000/`
- Check firewall rules
- Ensure ESP and server are on same network

### Display Shows "WiFi Failed"
- Press RESET button on ESP
- Check WiFi credentials
- Serial monitor shows detailed errors

## Power Options

### USB Power
- Connect to computer USB port
- Or use USB phone charger (5V, 1A minimum)

### Battery Power
- Use 18650 Li-ion battery with TP4056 charging module
- Or USB power bank
- Current draw: ~80mA average

## Enclosure Ideas

- 3D printed case with OLED window
- Retro cassette tape case
- Small project box with clear lid
- Wall-mounted frame

## Customization

### Change Display Modes
Edit the `DisplayMode` enum and `updateDisplay()` function.

### Add More Sensors
- Temperature sensor for "market temperature"
- RGB LED for multi-color status
- Rotary encoder for menu navigation

### Different Display Sizes
Code supports 128x64 and 128x32 OLEDs. Adjust `SCREEN_HEIGHT`.

## Security Notes

- WiFi password is stored in plaintext in Arduino code
- Anyone with physical access can read the code
- For production, consider WiFiManager library for credential setup
- Server should be on local network or use HTTPS + auth

## Example Output

```
╔════════════════════════════════════╗
║     MELON TRADING BOT DISPLAY      ║
║         Hardware Terminal          ║
╚════════════════════════════════════╝

✓ WiFi Connected!
  IP: 192.168.1.105
  RSSI: -42 dBm

✓ Setup complete - Ready for trading!
```

## Support

For issues:
1. Check serial monitor (115200 baud)
2. Verify all connections
3. Test API endpoints in browser
4. Open issue on GitHub
