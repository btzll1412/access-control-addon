🔐 Access Control System for Home Assistant

A professional, self-hosted door access control system that runs on Home Assistant. Control multiple doors with RFID cards, PIN codes, schedules, and emergency lockdown features - all managed through a beautiful web dashboard.

![Access Control Dashboard](https://img.shields.io/badge/Home%20Assistant-Addon-blue) ![ESP32](https://img.shields.io/badge/ESP32-Compatible-green) ![License](https://img.shields.io/badge/License-MIT-yellow)

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
| 12V Wiegand RFID Reader | $15-30 | Amazon, AliExpress |
| 12V Door Strike/Electric Lock | $10-25 | Amazon, Home Depot |
| 5V Relay Module | $3-8 | Amazon, AliExpress |
| 12V to 5V Buck Converter (3A) | $3-6 | Amazon, AliExpress |
| 12V Power Supply (2A+) | $8-15 | Amazon, Home Depot |
| (Optional) 4x4 Keypad | $5-10 | Amazon, AliExpress |
| RFID Cards/Fobs | $0.30-1 each | Amazon, AliExpress |
| Jumper wires, terminal blocks | $5-10 | Amazon, AliExpress |

**Total per door:** ~$60-120 (compared to $2,000+ for commercial systems!)

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
3. Password: **Config123**
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
1. Connect 12V power supply to buck converter, readers, and relay
2. Connect buck converter 5V output to ESP32 VIN and relay VCC
3. Connect RFID reader to ESP32 (6 wires)
4. Connect relay to ESP32 and door strike
5. Test everything before final installation
6. Mount everything securely in enclosure

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

### Power Supply Architecture
```
12V Power Supply (2A+)
        │
        ├──→ RFID Readers (12V direct)
        ├──→ Relay COM (12V for door strikes)
        │
        └──→ Buck Converter (12V to 5V)
                    │
                    ├──→ ESP32 VIN pin (5V)
                    └──→ Relay Module VCC (5V)
```

### Visual Wiring Diagram (One Door)
```
                                    12V Power Supply (2A+)
                                           │
                    ┌──────────────────────┼────────────────────┐
                    │                      │                    │
                    │                      │                    │
                 [12V]                  [12V]              [12V to 5V]
                    │                      │               Buck Converter
                    │                      │                    │
                    │                      │                 [5V Out]
                    │                      │                    │
                    ▼                      ▼                    ├─────┬─────┐
            RFID Reader              Relay COM                 │     │     │
            ┌──────────┐                  │                    │     │     │
            │ 12V  ────┤◄─────────────────┘                   ▼     ▼     ▼
            │ GND  ────┤◄──────────────────────────────────  GND   VIN   VCC
            │ D0   ────┤──→ GPIO 16                          ESP32      Relay
            │ D1   ────┤──→ GPIO 17                          Board      Module
            │ LED  ────┤──→ GPIO 32                            │          │
            │ BEEP ────┤──→ GPIO 33                       GPIO 4 ────→ IN
            └──────────┘                                        │          │
                                                            [GND] ────→ GND
                                                                         │
                                                                      [NO]
                                                                         │
                                                                    Door Strike
                                                                    (12V when
                                                                     activated)
```

### Detailed Component Connections

#### 1️⃣ **12V Power Supply Distribution**

Connect your 12V power supply to:

| 12V Power Supply | Connects To | Wire Gauge | Purpose |
|-----------------|-------------|------------|---------|
| **12V +** | Buck Converter Input (+) | 18-20 AWG | Power for 5V conversion |
| **12V +** | RFID Reader VCC (Door 1) | 20-22 AWG | Reader power |
| **12V +** | RFID Reader VCC (Door 2) | 20-22 AWG | Reader power |
| **12V +** | Relay Module COM (Door 1) | 18 AWG | Door strike power |
| **12V +** | Relay Module COM (Door 2) | 18 AWG | Door strike power |
| **GND (-)** | All ground connections | 18-20 AWG | Common ground |

⚠️ **IMPORTANT:** Use a 12V power supply rated for at least 2A. If using two door strikes, 3A+ is recommended.

#### 2️⃣ **Buck Converter (12V → 5V)**

**Settings:**
- Input: 12V from power supply
- Output: **Adjust to exactly 5V** using the potentiometer (use multimeter!)
- Current rating: 3A minimum

| Buck Converter Pin | Connects To | Wire Gauge | Notes |
|-------------------|-------------|------------|-------|
| **IN+** | 12V Power Supply + | 18-20 AWG | Input power |
| **IN-** | 12V Power Supply GND | 18-20 AWG | Input ground |
| **OUT+** (5V) | ESP32 VIN pin | 20-22 AWG | **CRITICAL: Verify 5V first!** |
| **OUT+** (5V) | Relay Module VCC | 20-22 AWG | Relay logic power |
| **OUT-** (GND) | ESP32 GND | 20-22 AWG | Common ground |
| **OUT-** (GND) | Relay Module GND | 20-22 AWG | Common ground |

⚠️ **CRITICAL:** Before connecting to ESP32, use a multimeter to verify the buck converter output is **exactly 5V**. Too high can damage the ESP32!

#### 3️⃣ **RFID Reader (12V) Connections**

**Door 1 Reader → ESP32:**

| Reader Pin | Wire Color (typical) | Connects To | Purpose |
|------------|---------------------|-------------|---------|
| **VCC** | Red | 12V Power Supply + | 12V power |
| **GND** | Black | Power Supply GND | Ground |
| **D0** | White | ESP32 GPIO 16 | Wiegand data 0 |
| **D1** | Green | ESP32 GPIO 17 | Wiegand data 1 |
| **LED** | Yellow | ESP32 GPIO 32 | Green LED control (3.3V signal) |
| **BEEP** | Orange/Red | ESP32 GPIO 33 | Beeper/Red LED control (3.3V signal) |

**Door 2 Reader → ESP32 (if using 2 doors):**

| Reader Pin | Wire Color (typical) | Connects To | Purpose |
|------------|---------------------|-------------|---------|
| **VCC** | Red | 12V Power Supply + | 12V power |
| **GND** | Black | Power Supply GND | Ground |
| **D0** | White | ESP32 GPIO 25 | Wiegand data 0 |
| **D1** | Green | ESP32 GPIO 26 | Wiegand data 1 |
| **LED** | Yellow | ESP32 GPIO 14 | Green LED control |
| **BEEP** | Orange/Red | ESP32 GPIO 27 | Beeper/Red LED control |

📝 **Note:** Most 12V readers accept 3.3V logic signals from ESP32 for LED/BEEP control. If your reader doesn't work, you may need level shifters.

#### 4️⃣ **ESP32 Dev Board Connections**

| ESP32 Pin | Connects To | Purpose | Notes |
|-----------|-------------|---------|-------|
| **VIN** | Buck Converter 5V OUT (+) | Main power | Powers entire ESP32 |
| **GND** | Buck Converter GND | Ground | Multiple GND pins available |
| **GPIO 16** | Reader 1 D0 | Wiegand data | Input (internal pullup) |
| **GPIO 17** | Reader 1 D1 | Wiegand data | Input (internal pullup) |
| **GPIO 32** | Reader 1 LED | LED control | Output (3.3V) |
| **GPIO 33** | Reader 1 BEEP | Beeper control | Output (3.3V) |
| **GPIO 4** | Relay 1 IN | Door 1 control | Output (triggers relay) |
| **GPIO 25** | Reader 2 D0 | Wiegand data | Input (internal pullup) |
| **GPIO 26** | Reader 2 D1 | Wiegand data | Input (internal pullup) |
| **GPIO 14** | Reader 2 LED | LED control | Output (3.3V) |
| **GPIO 27** | Reader 2 BEEP | Beeper control | Output (3.3V) |
| **GPIO 5** | Relay 2 IN | Door 2 control | Output (triggers relay) |

📝 **Note:** Do NOT use the 3.3V pin to power anything - use VIN with 5V from buck converter.

#### 5️⃣ **Relay Module (5V) Connections**

**For Each Door (use 2-channel relay module for 2 doors):**

| Relay Module Pin | Connects To | Purpose | Notes |
|-----------------|-------------|---------|-------|
| **VCC** | Buck Converter 5V OUT | Logic power | 5V for relay coil |
| **GND** | Buck Converter GND | Ground | Common ground |
| **IN1** | ESP32 GPIO 4 | Door 1 trigger | Active LOW (triggers on 0V) |
| **IN2** | ESP32 GPIO 5 | Door 2 trigger | Active LOW (triggers on 0V) |
| **COM1** | 12V Power Supply + | Door 1 power source | Switches 12V to strike |
| **NO1** | Door Strike 1 (+) | Door 1 output | Normally Open contact |
| **COM2** | 12V Power Supply + | Door 2 power source | Switches 12V to strike |
| **NO2** | Door Strike 2 (+) | Door 2 output | Normally Open contact |

⚠️ **IMPORTANT:** 
- Use the **NO (Normally Open)** contact, not NC (Normally Closed)
- Most relay modules are "active LOW" - they trigger when GPIO sends 0V (LOW)
- The relay is just a switch - 12V never touches the ESP32!

#### 6️⃣ **Door Strike / Electric Lock**

**For Each Door Strike:**

| Door Strike Wire | Connects To | Purpose | Notes |
|-----------------|-------------|---------|-------|
| **+ (Red)** | Relay NO (Normally Open) | Power input | Gets 12V when unlocked |
| **- (Black)** | 12V Power Supply GND | Ground | Always connected |

**Strike Types:**
- **Fail-Secure** (Locked when no power) - Most common, use with NO contact
- **Fail-Safe** (Unlocked when no power) - Use with NC contact (for fire safety)

📝 **Note:** Check your strike's voltage (12V) and current rating. Some draw 500mA+, ensure your power supply can handle it.

---

### Complete Wiring Checklist

**Power Connections:**
- [ ] 12V power supply connected to buck converter input
- [ ] 12V power supply connected to all reader VCC pins
- [ ] 12V power supply connected to all relay COM terminals
- [ ] All grounds connected together (star ground configuration recommended)
- [ ] Buck converter adjusted to output exactly 5.0V (verified with multimeter)
- [ ] Buck converter 5V output connected to ESP32 VIN
- [ ] Buck converter 5V output connected to relay module VCC

**Signal Connections:**
- [ ] Reader 1: D0 → GPIO 16, D1 → GPIO 17
- [ ] Reader 1: LED → GPIO 32, BEEP → GPIO 33
- [ ] Reader 2: D0 → GPIO 25, D1 → GPIO 26
- [ ] Reader 2: LED → GPIO 14, BEEP → GPIO 27
- [ ] Relay 1: IN → GPIO 4
- [ ] Relay 2: IN → GPIO 5

**Output Connections:**
- [ ] Relay 1: COM → 12V+, NO → Strike 1 (+)
- [ ] Relay 2: COM → 12V+, NO → Strike 2 (+)
- [ ] Strike 1: (-) → GND
- [ ] Strike 2: (-) → GND

---

### Optional: 4x4 Keypad Wiring

If adding keypads for PIN code entry:

| Keypad Pin | ESP32 GPIO | Purpose |
|------------|------------|---------|
| **Row 1** | GPIO 12 | Keypad row 1 |
| **Row 2** | GPIO 13 | Keypad row 2 |
| **Row 3** | GPIO 15 | Keypad row 3 |
| **Row 4** | GPIO 2 | Keypad row 4 |
| **Col 1** | GPIO 18 | Keypad column 1 |
| **Col 2** | GPIO 19 | Keypad column 2 |
| **Col 3** | GPIO 21 | Keypad column 3 |
| **Col 4** | GPIO 22 | Keypad column 4 |

📝 **Note:** Keypads don't need external power - ESP32 provides 3.3V through GPIO pins.

---

### Shopping List (One Door System)

**Essential Components:**
- [ ] ESP32 Dev Board (ESP32-WROOM-32)
- [ ] 12V Wiegand RFID Reader (e.g., Standard 125hz Readers)
- [ ] 12V Electric Door Strike (e.g., Adams Rite 7400)
- [ ] 5V 2-Channel Relay Module
- [ ] 12V to 5V Buck Converter (3A, adjustable)
- [ ] 12V 2A Power Supply (or 3A for 2 doors)
- [ ] RFID Cards/Key Fobs (10-20 pack)
- [ ] Jumper wires (male-to-female, 20cm, various colors)
- [ ] Terminal blocks (screw terminals for 12V connections)
- [ ] Project enclosure (to house ESP32, relay, buck converter)

**Optional Components:**
- [ ] 4x4 Matrix Keypad
- [ ] Cat5e/Cat6 cable (for running wires through walls)
- [ ] Wire connectors, ferrules, heat shrink
- [ ] Multimeter (for testing voltages)
- [ ] Label maker (for labeling wires)

**Estimated Total Cost:** $60-100 per door

---

### Installation Tips

1. **Test on bench first** - Wire everything up on a table before installing in walls
2. **Use proper wire gauge** - 18 AWG for power, 22-24 AWG for signals
3. **Label everything** - Use tape or labels on wires before running through walls
4. **Secure connections** - Use terminal blocks or solder + heat shrink, not just twist
5. **Weatherproof outdoor installations** - Use IP65 enclosures for outdoor readers
6. **Cable management** - Use cable ties, conduit, or wire channels
7. **Leave slack** - Extra wire for future adjustments
8. **Document your installation** - Take photos of wiring for future reference

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
- **Unlock duration** - How long door stays unlocked (default 3 seconds, adjustable)

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
- ❌ **Buck converter voltage** → Verify it's outputting 5V, not higher/lower
- ❌ **Unlock duration too short** → Increase to 5000ms in door settings
- ✅ **Test relay** → Manual unlock from dashboard - does relay click?
- ✅ **Check voltage at strike** → Should see 12V when activated

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

### ESP32 randomly reboots or unstable

**Solutions:**
- ❌ **Insufficient power** → Buck converter may be undersized, use 3A minimum
- ❌ **Voltage drop** → Check wiring from buck converter to ESP32 VIN
- ❌ **Bad power supply** → Cheap 12V adapters can be noisy, use quality supply
- ❌ **EMI from relay** → Add 0.1µF capacitor across relay coil
- ✅ **Check voltage under load** → Measure 5V at ESP32 VIN while relay activates

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
│   ├── boot_app0.bin                # Boot application
│   └── README.md                    # Flasher instructions
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
- **Documentation**: [Full Docs](./DOCS.md)

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
