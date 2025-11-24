# 🔐 ESP32 Access Control System - Web Flasher

Flash ESP32 boards directly from your browser - no Arduino IDE needed!

![Version](https://img.shields.io/badge/version-2.0-blue)
![ESP32](https://img.shields.io/badge/ESP32-compatible-green)
![License](https://img.shields.io/badge/license-MIT-green)

---

## 🚀 Quick Start

### **Visit the Web Flasher:**
👉 **[https://btzll1412.github.io/access-control-addon/esp32-flasher/](https://btzll1412.github.io/access-control-addon/esp32-flasher/)**

### **Flashing Steps:**

1. **Connect your ESP32 via USB**
2. **Click "INSTALL FIRMWARE"** on the web flasher
3. **Select your COM port** from the browser prompt
4. **Wait 2-3 minutes** for flashing to complete
5. **Connect to WiFi:** `AccessControl-Setup` (password: `Config123`)
6. **Configure at:** [http://192.168.4.1](http://192.168.4.1)

---

## 📦 What You Need

### **Hardware Requirements:**

| Component | Specification | Notes |
|-----------|---------------|-------|
| **ESP32 Board** | ESP32-WROOM-32 or ESP32-S3 | 16MB Flash recommended |
| **USB Cable** | Data cable (not charge-only) | Must support data transfer |
| **Relay Module** | 2-Channel 5V/12V | With optocoupler isolation |
| **Power Supply** | 12V DC, 2A minimum | For relays and locks |
| **Wiegand Readers** | RC522 or PN532 RFID | Up to 2 readers per board |
| **Keypads** | 4x4 Matrix Keypad | Up to 2 keypads per board |
| **Electric Locks** | 12V solenoid or magnetic | 2 doors per board |

### **Software Requirements:**

- **Google Chrome** or **Microsoft Edge** browser (Web Serial API support)
- **CH340/CP2102 driver** (usually auto-installs on Windows 10+)

---

## 🔌 Hardware Wiring

### **Complete Wiring Diagram:**

```
┌─────────────────────────────────────────────────────────────────────┐
│                          ESP32 WIRING                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌─────────────────┐                                                │
│  │    ESP32 Board  │                                                │
│  │                 │                                                │
│  │ GPIO 13 ────────┼──→ Relay 1 IN (Door 1)                       │
│  │ GPIO 12 ────────┼──→ Relay 2 IN (Door 2)                       │
│  │                 │                                                │
│  │ GPIO 19 ────────┼──→ Buzzer (+)                                │
│  │ GND ────────────┼──→ Buzzer (-)                                │
│  │                 │                                                │
│  │ GPIO 2  ────────┼──→ Status LED (+) ──→ 220Ω ──→ GND          │
│  │                 │                                                │
│  └─────────────────┘                                                │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                   DOOR 1 WIEGAND READER                        │ │
│  ├────────────────────────────────────────────────────────────────┤ │
│  │ ESP32 GPIO 21 (SDA) ──→ Reader D0                             │ │
│  │ ESP32 GPIO 22 (SCL) ──→ Reader D1                             │ │
│  │ ESP32 3.3V ───────────→ Reader VCC                            │ │
│  │ ESP32 GND ────────────→ Reader GND                            │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                   DOOR 2 WIEGAND READER                        │ │
│  ├────────────────────────────────────────────────────────────────┤ │
│  │ ESP32 GPIO 32 ─────────→ Reader D0                            │ │
│  │ ESP32 GPIO 33 ─────────→ Reader D1                            │ │
│  │ ESP32 3.3V ────────────→ Reader VCC                           │ │
│  │ ESP32 GND ─────────────→ Reader GND                           │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                       KEYPAD 1 (Door 1)                        │ │
│  ├────────────────────────────────────────────────────────────────┤ │
│  │ Rows:    GPIO 14, 27, 26, 25                                  │ │
│  │ Columns: GPIO 23, 18, 5, 17                                   │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                       KEYPAD 2 (Door 2)                        │ │
│  ├────────────────────────────────────────────────────────────────┤ │
│  │ Rows:    GPIO 15, 4, 16, 34                                   │ │
│  │ Columns: GPIO 35, 36, 39, 25                                  │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                      RELAY MODULE                              │ │
│  ├────────────────────────────────────────────────────────────────┤ │
│  │ ESP32 GPIO 13 ──→ Relay 1 IN                                  │ │
│  │ ESP32 GPIO 12 ──→ Relay 2 IN                                  │ │
│  │ ESP32 3.3V ────→ Relay VCC                                    │ │
│  │ ESP32 GND ─────→ Relay GND                                    │ │
│  │                                                                 │ │
│  │ Relay 1 COM ───→ 12V Power (+)                                │ │
│  │ Relay 1 NO ────→ Door Lock 1 (+)                              │ │
│  │ Door Lock 1 (-)─→ 12V Power (-)                               │ │
│  │                                                                 │ │
│  │ Relay 2 COM ───→ 12V Power (+)                                │ │
│  │ Relay 2 NO ────→ Door Lock 2 (+)                              │ │
│  │ Door Lock 2 (-)─→ 12V Power (-)                               │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘
```

### **Visual Wiring Diagram:**

```
                    ┌───────────────────┐
                    │   12V Power Supply │
                    └────┬─────────┬─────┘
                         │         │
                    12V+ │         │ GND
                         │         │
              ┌──────────┴─────────┴────────┐
              │   2-Channel Relay Module     │
              │                               │
              │  IN1  IN2  VCC  GND          │
              └───┬───┬────┬────┬────────────┘
                  │   │    │    │
          GPIO13 ─┘   │    │    └─ ESP32 GND
          GPIO12 ─────┘    │
          ESP32 3.3V ──────┘

                    ┌───────────────┐
                    │   ESP32 Board │
                    │               │
         ┌──────────┤ GPIO 21 (SDA) ├──→ Reader 1 D0
         │  ┌───────┤ GPIO 22 (SCL) ├──→ Reader 1 D1
         │  │   ┌───┤ GPIO 32       ├──→ Reader 2 D0
         │  │   │┌──┤ GPIO 33       ├──→ Reader 2 D1
         │  │   ││  │               │
         │  │   ││  │ GPIO 13       ├──→ Relay 1
         │  │   ││  │ GPIO 12       ├──→ Relay 2
         │  │   ││  │               │
         │  │   ││  │ GPIO 19       ├──→ Buzzer (+)
         │  │   ││  │ GPIO 2        ├──→ LED (+)
         │  │   ││  │               │
         │  │   ││  │ 3.3V          ├──→ Readers VCC
         │  │   ││  │ GND           ├──→ All GNDs
         │  │   ││  └───────────────┘
         │  │   ││
         │  │   ││  ┌─────────────┐
         │  │   └┼──┤ RFID Reader │ (Door 2)
         │  │    └──┤    D0  D1   │
         │  │       │   VCC  GND  │
         │  │       └─────────────┘
         │  │
         │  │       ┌─────────────┐
         │  └───────┤ RFID Reader │ (Door 1)
         └──────────┤    D0  D1   │
                    │   VCC  GND  │
                    └─────────────┘
```

---

## 🔧 Detailed Setup Instructions

### **1. Hardware Assembly**

#### **Step 1: Connect Wiegand Readers**

**Door 1 Reader:**
```
Reader Pin    →    ESP32 Pin
─────────────────────────────
D0 (Green)    →    GPIO 21
D1 (White)    →    GPIO 22
VCC (Red)     →    3.3V
GND (Black)   →    GND
```

**Door 2 Reader:**
```
Reader Pin    →    ESP32 Pin
─────────────────────────────
D0 (Green)    →    GPIO 32
D1 (White)    →    GPIO 33
VCC (Red)     →    3.3V
GND (Black)   →    GND
```

#### **Step 2: Connect Relay Module**

```
Relay Pin     →    Connection
─────────────────────────────────────
IN1           →    ESP32 GPIO 13
IN2           →    ESP32 GPIO 12
VCC           →    ESP32 3.3V
GND           →    ESP32 GND

COM1          →    12V Power (+)
NO1           →    Door Lock 1 (+)
COM2          →    12V Power (+)
NO2           →    Door Lock 2 (+)

Lock 1 (-)    →    12V Power (-)
Lock 2 (-)    →    12V Power (-)
```

#### **Step 3: Connect Keypad 1 (Optional)**

**4x4 Matrix Keypad for Door 1:**
```
Keypad Pin    →    ESP32 Pin
─────────────────────────────
Row 1         →    GPIO 14
Row 2         →    GPIO 27
Row 3         →    GPIO 26
Row 4         →    GPIO 25
Col 1         →    GPIO 23
Col 2         →    GPIO 18
Col 3         →    GPIO 5
Col 4         →    GPIO 17
```

#### **Step 4: Connect Buzzer & LED**

```
Component     →    Connection
─────────────────────────────────
Buzzer (+)    →    GPIO 19
Buzzer (-)    →    GND
LED (+)       →    GPIO 2 → 220Ω → GND
```

---

### **2. Flash Firmware**

#### **Method A: Web Flasher (Recommended)**

1. Visit: **[https://btzll1412.github.io/access-control-addon/esp32-flasher/](https://btzll1412.github.io/access-control-addon/esp32-flasher/)**
2. Connect ESP32 via USB
3. Click **"INSTALL FIRMWARE"**
4. Select COM port
5. Wait for completion (2-3 minutes)

#### **Method B: Arduino IDE (Advanced)**

1. Download `AccessControl.ino` from `/SOURCE_CODE/`
2. Install ESP32 board support in Arduino IDE
3. Select **Board:** "ESP32 Dev Module" or "ESP32-S3"
4. Select **Partition Scheme:** "Huge APP (3MB No OTA)"
5. Upload to board

---

### **3. Initial Configuration**

#### **Step 1: Connect to Setup WiFi**

After flashing, the ESP32 creates a WiFi access point:

```
SSID:     AccessControl-Setup
Password: Config123
```

**Connect your phone/laptop to this network.**

#### **Step 2: Configure via Web Interface**

1. Open browser and go to: **http://192.168.4.1**
2. Enter your WiFi credentials:
   - **SSID:** Your home/office WiFi name
   - **Password:** Your WiFi password
3. Set **Controller IP Address** (the computer running the controller software)
4. Click **"Save Configuration"**
5. ESP32 will reboot and connect to your WiFi

#### **Step 3: Adopt Board in Controller**

1. Open the Access Control Controller Dashboard
2. Go to **📡 Boards** tab
3. Look for **"Pending Boards"** notification
4. Click **"✅ Adopt Boards"**
5. Assign meaningful names to Door 1 and Door 2
6. Click **"Adopt"**

---

## 📚 Features

### **Access Control:**
- ✅ **Dual-door support** (2 doors per ESP32 board)
- ✅ **Wiegand RFID readers** (26-bit & 34-bit support)
- ✅ **PIN code keypads** (4-8 digit PINs)
- ✅ **Temporary access codes** (one-time, limited, or unlimited uses)
- ✅ **Per-door usage tracking** for temp codes
- ✅ **User schedules** (time restrictions)
- ✅ **Door schedules** (unlock/controlled/locked by time)

### **Management:**
- ✅ **Web-based controller** dashboard
- ✅ **User groups** with door permissions
- ✅ **Emergency lockdown/unlock** (board-wide or per-door)
- ✅ **Real-time access logs** with filtering
- ✅ **Offline operation** (ESP32 works without controller)
- ✅ **Configurable unlock duration** per door (0.5-30 seconds)

### **Hardware:**
- ✅ **Relay control** with adjustable duration
- ✅ **Audible feedback** (buzzer)
- ✅ **Visual feedback** (LED)
- ✅ **Dual keypad support** (one per door)
- ✅ **Dual Wiegand reader support**

---

## 🛠️ Troubleshooting

### **Problem: Can't Connect to COM Port**

**Solution:**
1. Install CH340/CP2102 driver:
   - Windows: [Download here](https://www.wch-ic.com/downloads/CH341SER_EXE.html)
   - Mac: [Download here](https://github.com/adrianmihalko/ch340g-ch34g-ch34x-mac-os-x-driver)
2. Try different USB cable (must be data cable, not charge-only)
3. Try different USB port
4. Restart computer

### **Problem: Flash Failed**

**Solution:**
1. Hold **BOOT** button on ESP32 while clicking "Install"
2. Check if ESP32 is in bootloader mode (LED should blink)
3. Try lower baud rate (115200 instead of 921600)
4. Ensure no other program is using the COM port

### **Problem: Can't See AccessControl-Setup WiFi**

**Solution:**
1. Wait 30 seconds after flashing
2. Power cycle the ESP32 (unplug and replug USB)
3. Check if LED is blinking (indicates AP mode)
4. Look for WiFi with slightly different name (MAC address suffix)

### **Problem: Door Won't Unlock**

**Solution:**
1. Check relay wiring (COM, NO pins)
2. Verify 12V power supply to relays
3. Check door lock polarity
4. Test relay manually (should click when activated)
5. Verify unlock duration setting (default 3 seconds)

### **Problem: Card Not Recognized**

**Solution:**
1. Verify Wiegand wiring (D0/D1 to correct GPIOs)
2. Check if card is added to user account in controller
3. Test card format (26-bit vs 34-bit)
4. Check if reader has power (LED should light when card presented)

### **Problem: Keypad Not Working**

**Solution:**
1. Verify row/column pin connections
2. Test keypad with multimeter (should show continuity when pressed)
3. Check if keypad is 4x4 matrix type
4. Verify GPIO pins are correct for your door

---

## 📖 Source Code

The complete ESP32 source code is available in this repository:

📁 **`/SOURCE_CODE/AccessControl.ino`** - Full Arduino sketch

---

## 🔗 Related Links

- **Main Repository:** [Access Control System](https://github.com/btzll1412/access-control-addon)
- **Controller Software:** See main repo `/app/` folder
- **Documentation:** See main repo `/DOCS/` folder

---

## 📝 License

MIT License - See LICENSE file for details

---

## 🤝 Contributing

Contributions welcome! Please open an issue or pull request.

---

## 💬 Support

- **Issues:** [GitHub Issues](https://github.com/btzll1412/access-control-addon/issues)
- **Discussions:** [GitHub Discussions](https://github.com/btzll1412/access-control-addon/discussions)

---

## 🎉 Credits

Built with ❤️ using ESP32, Arduino, and Web Serial API

**Components Used:**
- ESP32-IDF
- Wiegand Library
- Keypad Library
- ArduinoJson
- ESPAsyncWebServer

---

**Last Updated:** November 2024
**Version:** 2.0
