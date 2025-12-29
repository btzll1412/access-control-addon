# ESP32 Standard Firmware

Firmware files for standard ESP32 boards with 4MB Flash.

## Required Files

- `bootloader.bin` - Included
- `partitions.bin` - Included
- `boot_app0.bin` - Included
- `firmware.bin` - Included (needs updating after code changes)

## How to Update Firmware

### Arduino IDE Settings

1. **Board:** "ESP32 Dev Module"
2. **Flash Size:** "4MB (32Mb)"
3. **Flash Mode:** "QIO"
4. **Partition Scheme:** "Default 4MB with spiffs"
5. **Upload Speed:** "921600"

### Export Compiled Binary

1. Open `SOURCE_CODE/AccessControlESP32.ino` in Arduino IDE
2. Go to **Sketch > Export Compiled Binary** (or press Ctrl+Alt+S)
3. Arduino will create a `build` folder with the compiled files
4. Copy these files to this directory:
   - `AccessControlESP32.ino.bootloader.bin` -> rename to `bootloader.bin`
   - `AccessControlESP32.ino.partitions.bin` -> rename to `partitions.bin`
   - `AccessControlESP32.ino.bin` -> rename to `firmware.bin`

### Finding the Files

After "Export Compiled Binary", look in:
- **Windows:** `Documents/Arduino/SOURCE_CODE/build/esp32.esp32.esp32/`
- **Mac:** `~/Documents/Arduino/SOURCE_CODE/build/esp32.esp32.esp32/`
- **Linux:** `~/Arduino/SOURCE_CODE/build/esp32.esp32.esp32/`

Or check the Arduino IDE output console for the exact path.

## Firmware Version

Current version: **3.2.3**

Features:
- Non-blocking network operations
- Fast card processing (~11ms loop time)
- NTP time sync with auto-retry
- Reliable MAC address detection
- Loop health diagnostics
