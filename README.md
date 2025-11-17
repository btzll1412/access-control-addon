# 🔐 Access Control System for Home Assistant

A professional, self-hosted door access control system that runs on Home Assistant. Control multiple doors with RFID cards, PIN codes, schedules, and emergency lockdown features - all managed through a beautiful web dashboard.

![Access Control Dashboard](https://img.shields.io/badge/Home%20Assistant-Addon-blue) ![ESP32](https://img.shields.io/badge/ESP32-Compatible-green) ![License](https://img.shields.io/badge/License-MIT-yellow)

---

## 📸 Screenshots

*(Add screenshots of your dashboard here)*

---

## ✨ What Does This Do?

This system lets you:

- **🚪 Control doors remotely** - Unlock doors from your phone or computer
- **💳 Use RFID cards** - Swipe cards to open doors (like a hotel keycard)
- **🔢 Use PIN codes** - Enter a code on a keypad to unlock
- **👥 Manage users** - Add/remove people and their access cards
- **📅 Set schedules** - Doors automatically unlock during business hours, lock at night
- **🚨 Emergency controls** - Instantly lock or unlock all doors in emergencies
- **📊 View logs** - See who opened which door and when
- **🏢 Create groups** - Organize users by department or access level

---

## 🎯 Who Is This For?

- **Small businesses** - Office access control without expensive monthly fees
- **Home offices** - Secure entry without keys
- **Makerspaces** - Member access management
- **Apartment buildings** - Tenant door control
- **Anyone who wants** - Professional access control without a subscription

---

## 💰 Cost Comparison

| Traditional System | This System |
|-------------------|-------------|
| $2,000-5,000+ upfront | ~$50-150 per door |
| $50-100/month subscription | $0/month (self-hosted) |
| Vendor lock-in | You own everything |
| Limited customization | Fully customizable |

---

## 🛠️ What You Need

### For the Server (Home Assistant):

- **Home Assistant** installed (on Raspberry Pi, old computer, or anything that runs HA)
- **This add-on** (free, installs in 2 minutes)

### For Each Door:

| Item | Approximate Cost | Where to Buy |
|------|-----------------|--------------|
| ESP32 Dev Board | $6-12 | Amazon, AliExpress |
| Wiegand RFID Reader | $15-30 | Amazon, AliExpress |
| Door Strike/Relay | $10-25 | Amazon, Home Depot |
| 12V Power Supply | $8-15 | Amazon, Home Depot |
| (Optional) Keypad | $5-10 | Amazon, AliExpress |
| RFID Cards/Fobs | $0.30-1 each | Amazon, AliExpress |

**Total per door:** ~$50-100 (compared to $2,000+ for commercial systems!)

---

## 🚀 Quick Start Guide

### Step 1: Install Home Assistant Add-on (5 minutes)

1. **Open Home Assistant**
2. Go to **Settings** → **Add-ons** → **Add-on Store**
3. Click the **⋮** (three dots, top right) → **Repositories**
4. Add this URL:
```
   https://github.com/btzll1412/access-control-addon
```
5. Click **"Access Control System"** from the list
6. Click **"Install"** (wait 2-3 minutes)
7. Turn on **"Start on boot"** and **"Show in sidebar"**
8. Click **"Start"**
9. Click **"Open Web UI"** - You'll see the dashboard! ✨

### Step 2: Flash Your ESP32 Board (5 minutes)

**The Easy Way - No Software Needed:**

1. **Visit our Web Flasher:** [https://btzll1412.github.io/access-control-addon/esp32-flasher/](https://btzll1412.github.io/access-control-addon/esp32-flasher/)
2. **Connect your ESP32** to your computer with a USB cable
3. Click the big **"⚡ INSTALL FIRMWARE"** button
4. **Select your COM port** from the popup (usually shows as "USB Serial" or "CP2102")
5. Click **"Connect"**
6. Wait 1-2 minutes while it flashes
7. **Done!** 🎉

**Troubleshooting:**
- ❌ No COM port showing? → Install [CH340 Driver](https://sparks.gogo.co.nz/ch340.html) or [CP2102 Driver](https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers)
- ❌ "Not supported browser"? → Use Google Chrome or Microsoft Edge (not Firefox/Safari)

### Step 3: Connect ESP32 to WiFi (3 minutes)

After flashing:

1. ESP32 creates a WiFi network called **"AccessControl-Setup"**
2. **Connect to this WiFi** on your phone/computer
3. Password: **12345678**
4. A setup page should open automatically (if not, visit **http://192.168.4.1**)
5. Enter:
   - Your home WiFi name (SSID)
   - Your home WiFi password
   - Your Home Assistant IP address (find it in HA: Settings → System → Network)
6. Click **"Save & Reboot"**
7. ESP32 restarts and connects to your network

### Step 4: Adopt the Board (2 minutes)

1. Go back to the **Access Control dashboard** in Home Assistant
2. You'll see a yellow notification: **"New Boards Waiting for Adoption"**
3. Click **"✅ Adopt Boards"**
4. Give your board a name (e.g., "Front Door Board")
5. Name the two doors (e.g., "Front Door" and "Back Door")
6. Click **"Adopt"**
7. **Your board is now online!** 🎉

### Step 5: Wire Up Your Hardware (30-60 minutes)

See the **[Wiring Guide](#-wiring-guide)** section below for detailed diagrams.

Basic steps:
1. Connect RFID reader to ESP32 (6 wires)
2. Connect door strike to ESP32 (2 wires)
3. Connect power supply
4. Mount everything securely
5. Test!

### Step 6: Add Your First User (2 minutes)

1. In the dashboard, click **"👥 Users"** tab
2. Click **"➕ Add User"**
3. Enter name (e.g., "John Smith")
4. Click **"➕ Add Card"**
5. **Swipe your RFID card** on the reader - the number appears automatically!
   - (Or enter manually if needed)
6. Select which **groups** this user belongs to (access permissions)
7. Click **"💾 Save"**
8. **Try swiping the card!** The door should unlock! ✨

---

## 🔌 Wiring Guide

### Simple Wiring Diagram (One Door)
```
ESP32 Board                    RFID Reader
┌─────────────┐               ┌──────────────┐
│             │               │              │
│   GPIO 16 ──┼───────────────┤ D0 (White)   │
│   GPIO 17 ──┼───────────────┤ D1 (Green)   │
│   GPIO 32 ──┼───────────────┤ LED (Yellow) │
│   GPIO 33 ──┼───────────────┤ BEEP (Red)   │
│   5V      ──┼───────────────┤ VCC (Red)    │
│   GND     ──┼───────────────┤ GND (Black)  │
│             │               │              │
│   GPIO 4  ──┼───┐           └──────────────┘
│             │   │
└─────────────┘   │           Door Strike/Relay
                  │           ┌──────────────┐
                  └───────────┤ IN           │
                              │              │
                  12V ────────┤ VCC          │
                  GND ────────┤ GND          │
                              │              │
                              │ NO  ─────────┤─── Door Strike
                              │ COM ─────────┤─── 12V Power
                              └──────────────┘
```

### Detailed Wiring Table

#### Door 1 RFID Reader → ESP32

| Reader Pin | Wire Color (typical) | ESP32 Pin | Purpose |
|------------|---------------------|-----------|---------|
| D0 | White | GPIO 16 | Data 0 |
| D1 | Green | GPIO 17 | Data 1 |
| LED | Yellow | GPIO 32 | LED control (green light) |
| BEEP | Red | GPIO 33 | Beeper control (red light/buzzer) |
| VCC | Red | 5V | Power |
| GND | Black | GND | Ground |

#### Door 2 RFID Reader → ESP32 (if using 2 doors)

| Reader Pin | ESP32 Pin | Purpose |
|------------|-----------|---------|
| D0 | GPIO 25 | Data 0 |
| D1 | GPIO 26 | Data 1 |
| LED | GPIO 14 | LED control |
| BEEP | GPIO 27 | Beeper control |
| VCC | 5V | Power |
| GND | GND | Ground |

#### Door Strikes/Relays → ESP32

| Device | ESP32 Pin | Purpose |
|--------|-----------|---------|
| Door 1 Strike | GPIO 4 | Controls door 1 lock |
| Door 2 Strike | GPIO 5 | Controls door 2 lock |

#### Optional: 4x4 Keypad → ESP32

| Keypad | ESP32 Pin |
|--------|-----------|
| Row 1 | GPIO 12 |
| Row 2 | GPIO 13 |
| Row 3 | GPIO 15 |
| Row 4 | GPIO 2 |
| Col 1 | GPIO 18 |
| Col 2 | GPIO 19 |
| Col 3 | GPIO 21 |
| Col 4 | GPIO 22 |

### Power Supply

- **ESP32**: 5V via USB or 5V pin (500mA)
- **Door Strikes**: Usually 12V (check your specific strike - some are 5V, 9V, or 24V)
- **RFID Readers**: 5V from ESP32 is fine

**⚠️ IMPORTANT:** Door strikes pull a lot of current! Use a proper 12V power supply (2A+) and a relay module - **DO NOT** connect door strikes directly to ESP32!

---

## 📖 Detailed Features

### 🚪 Door Management

- **Two doors per ESP32 board** (expandable with more boards)
- **Manual unlock** from dashboard (emergency/visitors)
- **Door schedules**:
  - 🔓 **Unlocked** - Door stays open (business hours)
  - 🔐 **Controlled** - Requires card/PIN (after hours)
  - 🔒 **Locked** - Nobody gets in (closed/holidays)
- **Different schedules per day** (e.g., unlocked Mon-Fri 9am-5pm, locked weekends)
- **Unlock duration** - How long door stays unlocked (default 3 seconds)

### 👥 User Management

- **Unlimited users**
- **Multiple cards per user** (backup cards, key fobs)
- **Multiple PINs per user** (4-8 digits)
- **User status** - Active/Inactive (disable without deleting)
- **Valid date ranges** - Temporary access (contractors, guests)
- **CSV Import/Export** - Bulk add users from spreadsheet
- **User notes** - Add information (employee ID, phone number, etc.)

### 🏢 Access Groups

- **Organize users** by department, role, or access level
- **Assign doors to groups** (e.g., "Managers" can access all doors, "Staff" only lobby)
- **Color-coded** for easy visual management
- **One user, multiple groups** (flexible permissions)

### 📅 Time Schedules

- **Restrict WHEN users can access** doors
- **Day and time-based** (e.g., cleaning crew only Mon-Fri 6pm-10pm)
- **Multiple time ranges** per schedule
- **24/7 access by default** (if no schedule assigned)

### 🚨 Emergency Controls

- **🔒 Emergency Lockdown** - Instantly lock ALL doors (active shooter, security threat)
- **🔓 Emergency Evacuation** - Instantly unlock ALL doors (fire, emergency exit)
- **Per-door overrides** - Lock/unlock individual doors
- **Audit logging** - Records who activated emergency mode and when
- **Auto-reset timer** - Optional automatic return to normal (for evacuations)

### 📊 Access Logs

- **Complete history** of every access attempt
- **Filter by**:
  - User
  - Door
  - Date range
  - Access result (granted/denied)
  - Credential type (card/PIN/manual)
- **Search** across all fields
- **Real-time updates** - See activity as it happens
- **Granted/Denied tracking** - Security monitoring

### 🌐 Online/Offline Operation

- **Works even if internet is down!**
- ESP32 stores:
  - All user credentials locally
  - Door schedules
  - Current time (via NTP sync)
- **Syncs automatically** when connection restored
- **Heartbeat monitoring** - Dashboard shows board status (online/offline)

---

## 🎓 Usage Examples

### Example 1: Small Office

**Setup:**
- Front door (main entrance)
- Back door (loading dock)

**Groups:**
- "Everyone" - Access to front door (Mon-Fri 6am-8pm)
- "Management" - Access to both doors (24/7)
- "Cleaning Crew" - Access to both doors (Mon-Fri 6pm-10pm only)

**Users:**
- 10 employees with cards (Everyone group)
- 2 managers with cards (Management group)
- 1 cleaning person with card (Cleaning Crew group)

**Schedules:**
- **Business Hours (Mon-Fri 8am-6pm):** Front door = Unlocked, Back door = Controlled
- **After Hours (6pm-8am):** Both doors = Controlled
- **Weekends:** Both doors = Locked (except Management can still access)

### Example 2: Home Office

**Setup:**
- Office door with both RFID reader and keypad

**Users:**
- Yourself (card + PIN)
- Spouse (card + PIN)
- Kids (PIN only - no cards, easier to revoke)
- Dog walker (temporary card, valid for 1 month)

**Schedule:**
- Door always controlled (requires card/PIN)

### Example 3: Makerspace

**Setup:**
- Main entrance
- Workshop room

**Groups:**
- "Members" - Main entrance only
- "Workshop Certified" - Main entrance + workshop

**Schedules:**
- Main entrance: Unlocked during open hours, controlled other times
- Workshop: Always controlled (even during open hours)

---

## 🔧 Advanced Features

### CSV User Import

Bulk import users from a spreadsheet:

1. Download template: Click **"📥 Download Template"** in Users tab
2. Fill in Excel/Google Sheets:
```
   Name,Cards,PINs,Active,Valid From,Valid Until,Notes,Groups
   John Smith,12345678,1234,TRUE,2025-01-01,2025-12-31,Employee,Staff
   Jane Doe,87654321,5678|9999,TRUE,,,Manager,Staff|Management
```
3. Save as CSV
4. Click **"📤 Import CSV"**
5. Done! All users imported and synced to boards

### API Access

For developers - integrate with other systems:
```python
# Unlock door programmatically
import requests

response = requests.post('http://[HA-IP]:8100/api/doors/1/unlock')
```

See API documentation in [DOCS.md](./DOCS.md)

### Emergency Auto-Reset

For evacuations, set auto-reset timer:
1. Activate emergency unlock
2. Set timer (e.g., 30 minutes)
3. System automatically returns to normal after time expires
4. Useful for fire drills, evacuations

---

## 🐛 Troubleshooting

### ESP32 won't connect to WiFi

**Solutions:**
- ❌ **Wrong password** → ESP32 creates "AccessControl-Setup" WiFi again, reconnect and try again
- ❌ **5GHz WiFi** → ESP32 only works with 2.4GHz - make sure you're using 2.4GHz network
- ❌ **Hidden SSID** → ESP32 can't see hidden networks - unhide your WiFi temporarily
- ❌ **Special characters in WiFi name/password** → Try changing to simple alphanumeric

### Board shows offline in dashboard

**Solutions:**
- ✅ Check ESP32 has power (LED on)
- ✅ Check ESP32 connected to WiFi (visit http://[ESP32-IP]/)
- ✅ Check controller IP is correct on ESP32 web interface
- ✅ Ping ESP32 from Home Assistant terminal: `ping [ESP32-IP]`
- ✅ Check firewall isn't blocking port 8100

### Card doesn't work

**Solutions:**
- ❌ **Card not registered** → Add card number in dashboard first
- ❌ **User inactive** → Check user status is "Active"
- ❌ **User expired** → Check valid date range
- ❌ **Wrong access group** → Check user's groups have permission for this door
- ❌ **Outside schedule** → Check user's time schedule allows access now
- ✅ **Check logs** → See exact reason for denial in Access Logs tab

### Door doesn't unlock (card accepted but door stays locked)

**Solutions:**
- ❌ **Strike wiring** → Check relay connections, check 12V power
- ❌ **Relay backwards** → Try swapping NO/NC connections
- ❌ **Power supply** → Door strikes need lots of current - use 2A+ power supply
- ❌ **Unlock duration too short** → Increase to 5000ms in door settings
- ✅ **Test relay** → Manual unlock from dashboard - does relay click?

### Reader beeps red/card denied

Check the **Access Logs** tab - it tells you exactly why:
- "Unknown credential" → Card not in system
- "User inactive" → User was deactivated
- "Access denied - Schedule" → Outside allowed time window
- "Access denied - No permission" → User's group doesn't have access to this door

### Can't flash ESP32

**Solutions:**
- ❌ **Wrong browser** → Must use Chrome or Edge (not Firefox/Safari)
- ❌ **No COM port showing** → Install driver (see Step 2 above)
- ❌ **"Failed to connect"** → Hold BOOT button on ESP32 while clicking "Connect"
- ❌ **"Permission denied"** → Close Arduino IDE (can't have two programs using COM port)

---

## 🔒 Security Notes

### ⚠️ Important Security Considerations

1. **Change Default Password**: The WiFi setup password (12345678) should be changed in the ESP32 code before production use
2. **Network Security**: Place ESP32 boards on a separate VLAN if possible
3. **Physical Security**: ESP32 boards should be in locked enclosures
4. **HTTPS**: Consider setting up HTTPS for the web dashboard
5. **Backup**: Regularly backup your database (includes all users, logs, settings)

### 🛡️ What This System Protects Against

- ✅ Lost/stolen cards (deactivate instantly from dashboard)
- ✅ Unauthorized access (logs everything)
- ✅ After-hours access (schedules)
- ✅ Tailgating (one person per card swipe)

### ❌ What This System Does NOT Protect Against

- ❌ Physical attacks (breaking door, picking lock)
- ❌ Card cloning (Wiegand cards can be cloned - use HID iClass or similar for high security)
- ❌ Network attacks (secure your network!)
- ❌ Malicious insiders with physical ESP32 access

**For high-security applications**, use encrypted cards (HID iClass, DESFire) and consider adding video surveillance.

---

## 📁 Repository Structure
```
access-control-addon/
├── access_control/                  # Home Assistant add-on
│   ├── main.py                      # Backend server
│   ├── dashboard.html               # Web interface
│   ├── requirements.txt             # Python dependencies
│   └── ...
├── esp32-flasher/                   # ESP32 firmware flasher
│   ├── index.html                   # Web flasher interface
│   ├── manifest.json                # Flash configuration
│   ├── firmware.bin                 # ESP32 firmware
│   ├── bootloader.bin               # Bootloader
│   ├── partitions.bin               # Partition table
│   └── boot_app0.bin                # Boot application
├── CHANGELOG.md                     # Version history
├── DOCS.md                          # Detailed documentation
└── README.md                        # This file
```

---

## 🤝 Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

You are free to:
- ✅ Use commercially
- ✅ Modify
- ✅ Distribute
- ✅ Private use

---

## 🙏 Acknowledgments

- **Home Assistant Community** - For the amazing platform
- **ESP32 Community** - For hardware support and libraries
- **Wiegand Protocol** - Standard RFID interface
- **Contributors** - Everyone who helped make this better

---

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/btzll1412/access-control-addon/issues)
- **Discussions**: [GitHub Discussions](https://github.com/btzll1412/access-control-addon/discussions)
- **Email**: [your-email@example.com]

---

## 🗺️ Roadmap

### Coming Soon
- [ ] Mobile app for iOS/Android
- [ ] Telegram/WhatsApp notifications
- [ ] Facial recognition support
- [ ] Multi-factor authentication (card + PIN)
- [ ] Cloud sync (optional)
- [ ] Video intercom integration

### Future Ideas
- [ ] Biometric readers (fingerprint)
- [ ] License plate recognition
- [ ] Guest access QR codes
- [ ] Integration with Stripe (paid access)

---

## ⭐ Show Your Support

If this project helped you, please:
- ⭐ **Star this repository**
- 🐛 **Report bugs** you find
- 💡 **Suggest features** you'd like
- 📢 **Share** with others who might benefit

---

<div align="center">

**Built with ❤️ for the Home Assistant community**

[⬆ Back to Top](#-access-control-system-for-home-assistant)

</div>
```

---

## 🎨 **OPTIONAL: Add These Files Too**

### **LICENSE** file:
```
MIT License

Copyright (c) 2025 Betzalel

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
