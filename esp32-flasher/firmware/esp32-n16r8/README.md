# ESP32-S3 N16R8 Firmware

Firmware files for ESP32-S3 boards with 16MB Flash and 8MB PSRAM.

## Required Files (You Need to Generate These)

After compiling in Arduino IDE, you need these 4 files:
- `bootloader.bin`
- `partitions.bin`
- `boot_app0.bin` (already included)
- `firmware.bin`

## How to Generate Firmware Files

### Arduino IDE Settings

1. **Board:** "ESP32S3 Dev Module"
2. **USB CDC On Boot:** "Enabled"
3. **Flash Size:** "16MB (128Mb)"
4. **Flash Mode:** "QIO 80MHz"
5. **PSRAM:** "OPI PSRAM"
6. **Partition Scheme:** "16M Flash (3MB APP/9.9MB FATFS)" or "Default 4MB with spiffs"
7. **Upload Speed:** "921600"

### Export Compiled Binary

1. Open `SOURCE_CODE/AccessControleESP32N16R8.ino` in Arduino IDE
2. Go to **Sketch > Export Compiled Binary** (or press Ctrl+Alt+S)
3. Arduino will create a `build` folder with the compiled files
4. Copy these files to this directory:
   - `AccessControleESP32N16R8.ino.bootloader.bin` -> rename to `bootloader.bin`
   - `AccessControleESP32N16R8.ino.partitions.bin` -> rename to `partitions.bin`
   - `AccessControleESP32N16R8.ino.bin` -> rename to `firmware.bin`

### Finding the Files

After "Export Compiled Binary", look in:
- **Windows:** `Documents/Arduino/SOURCE_CODE/build/esp32.esp32.esp32s3/`
- **Mac:** `~/Documents/Arduino/SOURCE_CODE/build/esp32.esp32.esp32s3/`
- **Linux:** `~/Arduino/SOURCE_CODE/build/esp32.esp32.esp32s3/`

Or check the Arduino IDE output console for the exact path.

## Firmware Version

Current version: **3.2.3**

Features:
- Non-blocking network operations
- Fast card processing (~11ms loop time)
- NTP time sync with auto-retry
- Reliable MAC address detection
- Loop health diagnostics
