# 🔌 Hardware Wiring Guide

Complete hardware setup instructions for ESP32 Access Control System.

---

## 📦 Bill of Materials (BOM)

### **Per Door (Multiply by number of doors):**

| Qty | Component | Specification | Example Product | Price (Est.) |
|-----|-----------|---------------|-----------------|--------------|
| 1 | ESP32 Board | ESP32-WROOM-32 or ESP32-S3, 16MB Flash | ESP32 DevKit v1 | $8-15 |
| 1 | Relay Module | 2-Channel, 5V/12V, Optocoupler | SRD-05VDC-SL-C | $3-5 |
| 1 | Wiegand RFID Reader | 125kHz or 13.56MHz | HID ProxPoint Plus | $25-80 |
| 1 | Matrix Keypad | 4x4, Membrane | Standard 4x4 Keypad | $2-5 |
| 1 | Electric Lock | 12V Solenoid or Magnetic | 12V Solenoid Lock | $15-40 |
| 1 | Power Supply | 12V DC, 2A minimum | 12V 3A Adapter | $8-12 |
| 1 | Buzzer | 5V Active Buzzer | 5V Piezo Buzzer | $1-2 |
| 1 | LED | 3mm or 5mm, Any Color | Standard LED | $0.50 |
| 1 | Resistor | 220Ω, 1/4W | Standard Resistor | $0.10 |
| 1 | USB Cable | Micro-USB or USB-C (data) | Data Cable | $2-5 |
| - | Jumper Wires | Male-Female, 20cm | Dupont Wires | $5-10/set |
| - | Enclosure | Project Box | Plastic Enclosure | $5-15 |

**Total Cost per Door:** ~$75-200 (depending on quality)

---

## 🔧 Detailed Wiring Instructions

### **1. ESP32 to Relay Module**

The relay module controls the electric locks. Each relay needs 4 connections:

```
┌────────────────────────────────────────────┐
│         ESP32 → Relay Module               │
├────────────────────────────────────────────┤
│  ESP32 GPIO 13  →  Relay IN1 (Door 1)     │
│  ESP32 GPIO 12  →  Relay IN2 (Door 2)     │
│  ESP32 3.3V     →  Relay VCC              │
│  ESP32 GND      →  Relay GND              │
└────────────────────────────────────────────┘
```

**⚠️ IMPORTANT:**
- Use **3.3V**, NOT 5V (most ESP32 boards tolerate 5V but 3.3V is safer)
- Connect GND first to avoid floating pins
- Verify relay module is optocoupler-isolated (safer for ESP32)

---

### **2. Relay Module to Electric Locks**

Each relay switches 12V power to the door locks:

```
┌───────────────────────────────────────────────┐
│    Relay Module → Door Locks (High Side)      │
├───────────────────────────────────────────────┤
│                                                │
│  12V Power (+) ─────→ Relay 1 COM             │
│  Relay 1 NO ────────→ Door Lock 1 (+)         │
│  Door Lock 1 (-) ───→ 12V Power (-)           │
│                                                │
│  12V Power (+) ─────→ Relay 2 COM             │
│  Relay 2 NO ────────→ Door Lock 2 (+)         │
│  Door Lock 2 (-) ───→ 12V Power (-)           │
│                                                │
└───────────────────────────────────────────────┘
```

**Relay Pin Explanation:**
- **COM** (Common): Input power
- **NO** (Normally Open): Connects to COM when relay activated
- **NC** (Normally Closed): NOT USED (would reverse logic)

**Lock Types:**
- **Solenoid Lock:** Polarity doesn't matter
- **Magnetic Lock:** Polarity doesn't matter
- **Electric Strike:** Check polarity (usually marked + and -)

---

### **3. ESP32 to Wiegand Readers**

RFID readers use the Wiegand protocol (2 data wires):

**Door 1 Reader:**
```
┌────────────────────────────────────────┐
│   ESP32 GPIO 21 (SDA)  →  Reader D0   │
│   ESP32 GPIO 22 (SCL)  →  Reader D1   │
│   ESP32 3.3V           →  Reader VCC  │
│   ESP32 GND            →  Reader GND  │
└────────────────────────────────────────┘
```

**Door 2 Reader:**
```
┌────────────────────────────────────────┐
│   ESP32 GPIO 32        →  Reader D0   │
│   ESP32 GPIO 33        →  Reader D1   │
│   ESP32 3.3V           →  Reader VCC  │
│   ESP32 GND            →  Reader GND  │
└────────────────────────────────────────┘
```

**Wiegand Wire Colors (Standard):**
- **D0 (Data 0):** Green wire
- **D1 (Data 1):** White wire
- **VCC:** Red wire (3.3V or 5V - check your reader!)
- **GND:** Black wire

**⚠️ VOLTAGE WARNING:**
- Some readers need 5V, some work with 3.3V
- Check your reader specifications!
- If reader needs 5V for power, you can still use 3.3V for data lines
- Advanced: Use voltage level shifter if needed

---

### **4. ESP32 to Keypads (Optional)**

Each keypad requires 8 GPIO pins (4 rows + 4 columns):

**Keypad 1 (Door 1):**
```
┌─────────────────────────────────┐
│  Rows (Output):                 │
│    GPIO 14  →  Keypad Row 1     │
│    GPIO 27  →  Keypad Row 2     │
│    GPIO 26  →  Keypad Row 3     │
│    GPIO 25  →  Keypad Row 4     │
│                                  │
│  Columns (Input):               │
│    GPIO 23  →  Keypad Col 1     │
│    GPIO 18  →  Keypad Col 2     │
│    GPIO 5   →  Keypad Col 3     │
│    GPIO 17  →  Keypad Col 4     │
└─────────────────────────────────┘
```

**Keypad 2 (Door 2):**
```
┌─────────────────────────────────┐
│  Rows (Output):                 │
│    GPIO 15  →  Keypad Row 1     │
│    GPIO 4   →  Keypad Row 2     │
│    GPIO 16  →  Keypad Row 3     │
│    GPIO 34  →  Keypad Row 4     │
│                                  │
│  Columns (Input):               │
│    GPIO 35  →  Keypad Col 1     │
│    GPIO 36  →  Keypad Col 2     │
│    GPIO 39  →  Keypad Col 3     │
│    GPIO 25  →  Keypad Col 4     │
└─────────────────────────────────┘
```

**Keypad Layout:**
```
┌───┬───┬───┬───┐
│ 1 │ 2 │ 3 │ A │
├───┼───┼───┼───┤
│ 4 │ 5 │ 6 │ B │
├───┼───┼───┼───┤
│ 7 │ 8 │ 9 │ C │
├───┼───┼───┼───┤
│ * │ 0 │ # │ D │
└───┴───┴───┴───┘
```

**How to Identify Pins:**
- Most keypads have 8 pins in a row
- Left 4 pins = Rows (1-4)
- Right 4 pins = Columns (1-4)
- Test with multimeter if unsure

---

### **5. ESP32 to Buzzer & LED**

**Buzzer (Active 5V):**
```
┌──────────────────────────────┐
│  ESP32 GPIO 19  →  Buzzer +  │
│  ESP32 GND      →  Buzzer -  │
└──────────────────────────────┘
```

**Status LED:**
```
┌─────────────────────────────────────┐
│  ESP32 GPIO 2  →  LED Anode (+)     │
│  LED Cathode (-) → 220Ω → GND      │
└─────────────────────────────────────┘
```

**LED Polarity:**
- **Anode (+):** Longer leg
- **Cathode (-):** Shorter leg, flat side

**Resistor Calculation:**
- 220Ω for 3.3V and standard 20mA LED
- Formula: R = (V_source - V_led) / I_led
- Example: (3.3V - 2V) / 0.02A = 65Ω (use 220Ω for safety)

---

## 🔌 Complete Wiring Diagram

### **Full System Overview:**

```
                    ┌──────────────────────┐
                    │   12V Power Supply   │
                    │   (2A minimum)       │
                    └───────┬─────────┬────┘
                            │         │
                       12V+ │         │ GND
                            │         │
              ┌─────────────┴─────────┴──────────────┐
              │    2-Channel Relay Module             │
              │                                        │
              │  [Relay 1]           [Relay 2]        │
              │   COM NO NC          COM NO NC        │
              │    │  │               │  │            │
              │    │  └─→ Lock 1 +    │  └─→ Lock 2 +│
              │    │                   │               │
              │  Lock 1 - ────────────┴──→ 12V GND   │
              │  Lock 2 - ────────────────→ 12V GND   │
              │                                        │
              │  IN1  IN2  VCC  GND                   │
              └───┬───┬────┬────┬─────────────────────┘
                  │   │    │    │
          GPIO13 ─┘   │    │    └─ ESP32 GND
          GPIO12 ─────┘    │
          ESP32 3.3V ──────┘

┌───────────────────────────────────────────────────────────┐
│                     ESP32 DevKit                          │
│                                                            │
│  Power:                                                   │
│    USB 5V (from computer) or 5V external                 │
│                                                            │
│  Wiegand Reader 1 (Door 1):                              │
│    GPIO 21 (SDA) ──→ Reader D0 (Green)                  │
│    GPIO 22 (SCL) ──→ Reader D1 (White)                  │
│    3.3V ───────────→ Reader VCC (Red)                   │
│    GND ────────────→ Reader GND (Black)                 │
│                                                            │
│  Wiegand Reader 2 (Door 2):                              │
│    GPIO 32 ────────→ Reader D0 (Green)                  │
│    GPIO 33 ────────→ Reader D1 (White)                  │
│    3.3V ───────────→ Reader VCC (Red)                   │
│    GND ────────────→ Reader GND (Black)                 │
│                                                            │
│  Keypad 1 (Door 1) - 8 pins:                             │
│    GPIO 14,27,26,25 → Rows 1-4                          │
│    GPIO 23,18,5,17  → Cols 1-4                          │
│                                                            │
│  Keypad 2 (Door 2) - 8 pins:                             │
│    GPIO 15,4,16,34  → Rows 1-4                          │
│    GPIO 35,36,39,25 → Cols 1-4                          │
│                                                            │
│  Relay Control:                                          │
│    GPIO 13 ────────→ Relay 1 IN                         │
│    GPIO 12 ────────→ Relay 2 IN                         │
│                                                            │
│  Feedback:                                               │
│    GPIO 19 ────────→ Buzzer (+)                         │
│    GPIO 2  ────────→ LED (+) → 220Ω → GND              │
│    GND ────────────→ Buzzer (-), LED (-)                │
│                                                            │
└───────────────────────────────────────────────────────────┘
```

---

## ⚡ Power Requirements

### **Power Budget:**

| Component | Voltage | Current (mA) | Notes |
|-----------|---------|--------------|-------|
| ESP32 | 3.3V | 80-240 | Peak 240mA during WiFi |
| Wiegand Reader | 3.3-5V | 50-100 each | 2 readers = 200mA |
| Keypad | 3.3V | <10 each | Passive, minimal power |
| Relay Module | 3.3V | 15-20 each | Just for coil, 40mA total |
| Buzzer | 5V | 30 | Active buzzer |
| LED | 3.3V | 20 | With 220Ω resistor |
| **ESP32 Total** | **3.3V** | **~600mA** | **Regulated from USB 5V** |
| Electric Lock | 12V | 500-1000 | Per lock, separate power |

### **Power Supply Recommendations:**

**ESP32 System:**
- **Option 1:** USB power from computer (5V 500mA) - OK for testing
- **Option 2:** USB wall adapter 5V 2A - Better for permanent installation
- **Option 3:** Buck converter from 12V → 5V (LM2596) - Single power supply

**Door Locks:**
- **12V 2A minimum** (separate from ESP32)
- **12V 3A recommended** (handles 2 locks + margin)
- Must be separate from ESP32 power (different grounds OK)

---

## 🛡️ Safety Considerations

### **Electrical Safety:**

1. **Always disconnect power** before wiring
2. **Double-check polarity** on power supplies
3. **Use fuses** on 12V power lines (2A fast-blow)
4. **Insulate all connections** with heat shrink tubing
5. **Test with multimeter** before connecting components

### **Relay Safety:**

1. **Never exceed relay ratings** (typically 10A at 250VAC or 30VDC)
2. **Use flyback diodes** if switching inductive loads (optional, most relay modules include)
3. **Keep relay wiring separate** from low-voltage logic wiring

### **Lock Safety:**

1. **Fire code compliance:** Magnetic locks should fail-safe (unlock on power loss)
2. **Emergency release:** Install manual override buttons
3. **Backup battery:** Consider UPS for critical applications

---

## 🔧 Assembly Tips

### **Order of Assembly:**

1. ✅ **Test ESP32 first** - Flash firmware, verify WiFi
2. ✅ **Add buzzer & LED** - Test with manual commands
3. ✅ **Add one relay** - Test with manual unlock command
4. ✅ **Add one reader** - Test card reading
5. ✅ **Add one keypad** - Test PIN entry
6. ✅ **Add second door components**
7. ✅ **Install in enclosure**

### **Soldering Tips:**

- **Use flux** for cleaner joints
- **Tin wires first** before soldering to boards
- **Heat pad AND wire** simultaneously (2-3 seconds)
- **Use heat shrink** on all exposed connections

### **Enclosure Installation:**

- **Drill cable entry holes** before mounting
- **Use cable glands** or grommets for strain relief
- **Mount ESP32 on standoffs** (prevent shorts)
- **Separate high and low voltage** wiring
- **Label all wires** for future maintenance

---

## 📏 Wiring Length Limits

| Connection | Maximum Length | Notes |
|------------|----------------|-------|
| USB to ESP32 | 5 meters | Active USB extension OK |
| ESP32 to Relay | 2 meters | Logic signal, keep short |
| Relay to Lock | 30 meters | 12V power, use thick wire (18 AWG) |
| ESP32 to Reader | 100 meters | Wiegand is robust, use shielded twisted pair |
| ESP32 to Keypad | 2 meters | Matrix scanning, shorter is better |

**Wire Gauge Recommendations:**
- **Logic signals (3.3V):** 22-24 AWG
- **12V power to locks:** 18 AWG minimum
- **Long runs (>10m):** Use 16 AWG or thicker

---

## 🧪 Testing Checklist

Before final installation:

- [ ] ESP32 boots and creates WiFi AP
- [ ] Can configure WiFi credentials via web interface
- [ ] ESP32 connects to network and adopts to controller
- [ ] Buzzer beeps on boot
- [ ] LED blinks during operation
- [ ] Card 1 detected on Reader 1
- [ ] Card 2 detected on Reader 2
- [ ] Keypad 1 responds to button presses
- [ ] Keypad 2 responds to button presses
- [ ] Relay 1 activates for Door 1 unlock
- [ ] Relay 2 activates for Door 2 unlock
- [ ] Lock 1 opens when relay activated
- [ ] Lock 2 opens when relay activated
- [ ] Configurable unlock duration works
- [ ] Access logs recorded in controller

---

## 📚 Additional Resources

- **ESP32 Pinout:** [https://randomnerdtutorials.com/esp32-pinout-reference-gpios/](https://randomnerdtutorials.com/esp32-pinout-reference-gpios/)
- **Wiegand Protocol:** [https://www.hidglobal.com/sites/default/files/hid-understanding_card_data_formats-wp-en.pdf](https://www.hidglobal.com/sites/default/files/hid-understanding_card_data_formats-wp-en.pdf)
- **Relay Module Guide:** [https://www.instructables.com/How-to-use-a-relay/](https://www.instructables.com/How-to-use-a-relay/)

---

**Version:** 2.0  
**Last Updated:** November 2024
