# 🔐 ESP32 Access Control System

A complete access control solution with ESP32-based door controllers and a web-based management dashboard. Runs as a Home Assistant Add-on or standalone.

![Version](https://img.shields.io/badge/version-2.1-blue)
![ESP32](https://img.shields.io/badge/ESP32-compatible-green)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-Add--on-blue)
![License](https://img.shields.io/badge/license-MIT-green)

---

## ✨ Features

### **Access Control**
- ✅ Dual-door support (2 doors per ESP32 board)
- ✅ Wiegand RFID readers (26-bit & 34-bit support)
- ✅ PIN code keypads (4-8 digit PINs)
- ✅ Temporary access codes (one-time, limited, or unlimited uses)
- ✅ Per-door usage tracking for temp codes
- ✅ User schedules (time-based access restrictions)
- ✅ Door schedules (auto unlock/lock by time)

### **Management Dashboard**
- ✅ Web-based controller dashboard
- ✅ User & group management with door permissions
- ✅ Emergency lockdown/unlock (board-wide or per-door)
- ✅ Real-time access logs with filtering
- ✅ Schedule templates for easy configuration
- ✅ CSV import/export for users

### **Multi-Network Support**
- ✅ **Configurable controller address** - Set default IP/domain for boards
- ✅ **HTTP & HTTPS support** - Works with reverse proxies and Cloudflare tunnels
- ✅ **Remote board management** - Adopt boards on different networks
- ✅ Offline operation (ESP32 works without controller)

### **Hardware**
- ✅ Relay control with configurable unlock duration (0.5-30 seconds)
- ✅ Audible feedback (buzzer)
- ✅ Visual feedback (LED)
- ✅ Dual keypad support (one per door)
- ✅ Dual Wiegand reader support

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         CONTROLLER                                   │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              Home Assistant Add-on / Standalone              │   │
│  │                                                               │   │
│  │  • Web Dashboard (port 8100)                                 │   │
│  │  • User Management                                           │   │
│  │  • Access Logs                                               │   │
│  │  • Board Management                                          │   │
│  │  • Controller Settings (IP/Domain configuration)            │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                              │                                       │
│              HTTP/HTTPS (configurable)                              │
│                              │                                       │
└──────────────────────────────┼───────────────────────────────────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        │                      │                      │
        ▼                      ▼                      ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│   ESP32 #1    │    │   ESP32 #2    │    │   ESP32 #3    │
│   (2 doors)   │    │   (2 doors)   │    │   (2 doors)   │
│               │    │               │    │               │
│ • RFID Reader │    │ • RFID Reader │    │ • RFID Reader │
│ • Keypad      │    │ • Keypad      │    │ • Keypad      │
│ • Relays      │    │ • Relays      │    │ • Relays      │
└───────────────┘    └───────────────┘    └───────────────┘
```

---

## 🚀 Quick Start

### **1. Install the Controller**

#### Home Assistant Add-on (Recommended)
1. Add this repository to Home Assistant Add-on Store
2. Install "Access Control System"
3. Start the add-on
4. Access the dashboard via the add-on panel

#### Standalone (Docker)
```bash
docker run -d \
  -p 8100:8100 \
  -v access_control_data:/data \
  --name access-control \
  ghcr.io/btzll1412/access-control-addon
```

### **2. Flash ESP32 Boards**

👉 **[Web Flasher](https://btzll1412.github.io/access-control-addon/esp32-flasher/)**

1. Connect ESP32 via USB
2. Click "INSTALL FIRMWARE"
3. Select your COM port
4. Wait 2-3 minutes for flashing

### **3. Configure ESP32**

After flashing:
1. Connect to WiFi: `AccessControl-Setup` (password: `Config123`)
2. Open browser: http://192.168.4.1
3. Enter your WiFi credentials
4. Set controller IP address
5. Save and reboot

### **4. Adopt Boards**

1. Open the Controller Dashboard
2. Go to **📡 Boards** tab
3. Click **"✅ Adopt Boards"** when you see the notification
4. Configure controller address (see below)
5. Click **"Adopt"**

---

## ⚙️ Controller Settings (New in v2.1)

The **Controller Settings** feature allows you to configure the default address that boards use to communicate with the controller. This is essential for:

- Boards on different networks
- Using a domain name instead of IP
- HTTPS with reverse proxy (nginx, Cloudflare tunnel, etc.)

### **Setting Default Controller Address**

1. Go to **📡 Boards** tab
2. Click **"▼ Show Settings"** on the Controller Settings panel
3. Configure:
   - **Protocol:** HTTP or HTTPS
   - **Address:** IP address or domain name
   - **Port:** 8100 for HTTP, 443 for HTTPS (auto-detected)
4. Click **"💾 Save Default Settings"**

### **Example Configurations**

| Scenario | Protocol | Address | Port |
|----------|----------|---------|------|
| Local network | HTTP | 192.168.1.100 | 8100 |
| Cloudflare tunnel | HTTPS | access.example.com | 443 |
| Custom port | HTTPS | myserver.com | 8443 |

### **Per-Board Override**

When adopting a board, you can:
- ✅ **Use default** - Uses the saved controller settings
- ⬜ **Custom** - Enter a specific address for this board

This allows mixing local and remote boards in the same system.

---

## 📦 Hardware Requirements

| Component | Specification | Notes |
|-----------|---------------|-------|
| **ESP32 Board** | ESP32-WROOM-32 or ESP32-S3 | 16MB Flash recommended |
| **USB Cable** | Data cable (not charge-only) | Must support data transfer |
| **Relay Module** | 2-Channel 5V/12V | With optocoupler isolation |
| **Power Supply** | 12V DC, 2A minimum | For relays and locks |
| **Wiegand Readers** | RC522 or PN532 RFID | Up to 2 readers per board |
| **Keypads** | 4x4 Matrix Keypad | Up to 2 keypads per board |
| **Electric Locks** | 12V solenoid or magnetic | 2 doors per board |

---

## 🔌 Hardware Wiring

### **ESP32 Pin Assignments**

```
┌─────────────────────────────────────────────────────────────┐
│                      ESP32 PINOUT                            │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  RELAYS:                                                     │
│    GPIO 13 ──→ Relay 1 (Door 1)                             │
│    GPIO 12 ──→ Relay 2 (Door 2)                             │
│                                                              │
│  WIEGAND READER 1 (Door 1):                                 │
│    GPIO 21 ──→ D0                                           │
│    GPIO 22 ──→ D1                                           │
│                                                              │
│  WIEGAND READER 2 (Door 2):                                 │
│    GPIO 32 ──→ D0                                           │
│    GPIO 33 ──→ D1                                           │
│                                                              │
│  KEYPAD 1 (Door 1):                                         │
│    Rows:    GPIO 14, 27, 26, 25                             │
│    Columns: GPIO 23, 18, 5, 17                              │
│                                                              │
│  KEYPAD 2 (Door 2):                                         │
│    Rows:    GPIO 15, 4, 16, 34                              │
│    Columns: GPIO 35, 36, 39, 25                             │
│                                                              │
│  FEEDBACK:                                                   │
│    GPIO 19 ──→ Buzzer (+)                                   │
│    GPIO 2  ──→ Status LED (+) ──→ 220Ω ──→ GND             │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### **Relay Wiring**

```
ESP32                  Relay Module              Door Lock
─────                  ────────────              ─────────
GPIO 13 ──────────────→ IN1
GPIO 12 ──────────────→ IN2
3.3V ─────────────────→ VCC
GND ──────────────────→ GND
                        COM1 ←──── 12V (+)
                        NO1  ─────────────────→ Lock 1 (+)
                        COM2 ←──── 12V (+)      Lock 1 (-) ←── 12V (-)
                        NO2  ─────────────────→ Lock 2 (+)
                                                Lock 2 (-) ←── 12V (-)
```

---

## 🖥️ Dashboard Features

### **Boards Tab**
- View all connected boards with online/offline status
- Configure default controller settings
- Adopt pending boards
- Sync user database to boards
- Delete/edit board configuration

### **Doors Tab**
- Real-time door status
- Manual unlock button
- Emergency lock/unlock per door
- Configure unlock duration
- View door schedules

### **Users Tab**
- Add/edit users
- Assign RFID cards and PINs
- Set validity dates
- Assign to access groups
- Import/export via CSV

### **Groups Tab**
- Create access groups
- Assign doors to groups
- Color-coded organization

### **Schedules Tab**
- User schedules (when users can access)
- Door schedules (auto unlock times)

### **Temp Codes Tab**
- Create temporary access codes
- One-time, limited uses, or unlimited
- Per-door or global codes
- Time-limited validity

### **Emergency Tab**
- Board-wide emergency lockdown
- Board-wide emergency unlock
- Per-door overrides
- Auto-reset timers

### **Logs Tab**
- Real-time access log
- Filter by door, user, date
- Access granted/denied status

---

## 🛠️ Troubleshooting

### **Board Not Coming Online After Adoption**

**Possible causes:**
1. Controller address not reachable from board's network
2. Port blocked by firewall
3. HTTPS certificate issues

**Solutions:**
- Verify the controller address is correct
- For HTTPS, ensure port 443 is used (not 8100)
- Check if board can reach the controller IP/domain
- Look at board logs via serial monitor

### **Can't Connect to COM Port**

1. Install CH340/CP2102 driver
2. Try different USB cable (must be data cable)
3. Try different USB port
4. Restart computer

### **Flash Failed**

1. Hold BOOT button on ESP32 while clicking "Install"
2. Try lower baud rate
3. Ensure no other program is using the COM port

### **Can't See AccessControl-Setup WiFi**

1. Wait 30 seconds after flashing
2. Power cycle the ESP32
3. Check if LED is blinking (indicates AP mode)

### **Door Won't Unlock**

1. Check relay wiring (COM, NO pins)
2. Verify 12V power supply to relays
3. Check door lock polarity
4. Test relay manually
5. Verify unlock duration setting

### **Card Not Recognized**

1. Verify Wiegand wiring (D0/D1 to correct GPIOs)
2. Check if card is added to user account
3. Test card format (26-bit vs 34-bit)
4. Check if reader has power

---

## 🔗 Links

- **Web Flasher:** [https://btzll1412.github.io/access-control-addon/esp32-flasher/](https://btzll1412.github.io/access-control-addon/esp32-flasher/)
- **GitHub Repository:** [https://github.com/btzll1412/access-control-addon](https://github.com/btzll1412/access-control-addon)
- **Issues:** [GitHub Issues](https://github.com/btzll1412/access-control-addon/issues)

---

## 📝 Changelog

### v2.1 (December 2024)
- **New:** Configurable controller address for board adoption
- **New:** HTTP/HTTPS protocol selection
- **New:** Default controller settings in Boards tab
- **New:** Per-board controller address override
- **Fix:** Port defaulting (443 for HTTPS, 8100 for HTTP)

### v2.0 (November 2024)
- Initial release with full feature set
- Web flasher for ESP32
- Home Assistant Add-on support

---

## 📄 License

MIT License - See LICENSE file for details

---

## 🤝 Contributing

Contributions welcome! Please open an issue or pull request.

---

**Built with ❤️ using ESP32, Flask, and Home Assistant**
