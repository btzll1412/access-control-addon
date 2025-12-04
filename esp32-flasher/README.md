# ESP32 Firmware Web Flasher

Flash ESP32 boards directly from your browser - no Arduino IDE needed!

## 🚀 Quick Start

**Visit the web flasher:** Open `index.html` in Chrome or Edge

1. Connect your ESP32 via USB
2. **Select your board type** from the dropdown
3. Click "INSTALL FIRMWARE"
4. Select your COM port
5. Wait for flashing to complete
6. Connect to WiFi: `AccessControl-Setup` (password: `Config123`)
7. Configure at http://192.168.4.1

## 🔧 Supported Board Types

| Board | Flash | PSRAM | Source Code |
|-------|-------|-------|-------------|
| **ESP32 Standard** | 4MB | - | `AccessControlESP32.ino` |
| **ESP32-N16R8** | 16MB | 8MB | `AccessControleESP32N16R8.ino` |
| **ESP32-S3** | Varies | Varies | Requires adaptation |

## 📋 Requirements

- Google Chrome or Microsoft Edge browser
- ESP32 Dev Board (select your variant in the flasher)
- USB cable
- CH340/CP2102 driver (usually auto-installs)

## 📦 Folder Structure

```
esp32-flasher/
├── index.html              # Web flasher interface
├── manifests/              # Flash configurations
│   ├── esp32.json
│   ├── esp32-n16r8.json
│   └── esp32-s3.json
├── firmware/               # Compiled firmware files
│   ├── esp32/              # Standard ESP32
│   ├── esp32-n16r8/        # 16MB Flash variant
│   └── esp32-s3/           # S3 variant
└── SOURCE_CODE/            # Arduino source files
    ├── AccessControlESP32.ino
    └── AccessControleESP32N16R8.ino
```

## 🛠️ Adding Firmware for New Board Types

Each board type needs 4 files in its `firmware/` subfolder:

1. `bootloader.bin` - ESP32 bootloader
2. `partitions.bin` - Partition table
3. `boot_app0.bin` - Boot application
4. `firmware.bin` - Main firmware

### Compiling with Arduino IDE

1. Open the appropriate `.ino` file from `SOURCE_CODE/`
2. Select the correct board settings:
   - **ESP32 Standard**: Board "ESP32 Dev Module", 4MB flash
   - **ESP32-N16R8**: Board "ESP32 Dev Module", 16MB flash, PSRAM enabled
   - **ESP32-S3**: Board "ESP32S3 Dev Module"
3. Sketch → Export Compiled Binary
4. Copy the generated `.bin` files to the appropriate `firmware/` subfolder

## 🔌 Hardware Wiring

See main repository README for complete wiring diagrams.

## 🔄 Manual Flashing (Advanced)

If the web flasher doesn't work, use esptool.py:

```bash
# For ESP32 Standard
esptool.py --chip esp32 --port COM3 --baud 921600 \
  --before default_reset --after hard_reset write_flash \
  -z --flash_mode dio --flash_freq 40m --flash_size 4MB \
  0x1000 firmware/esp32/bootloader.bin \
  0x8000 firmware/esp32/partitions.bin \
  0xe000 firmware/esp32/boot_app0.bin \
  0x10000 firmware/esp32/firmware.bin
```

## 🔄 Updating Firmware

To update an existing board:
1. Visit the ESP32's web interface at http://[ESP32-IP]/
2. Go to /config to change settings
3. Or use the web flasher to completely reflash
