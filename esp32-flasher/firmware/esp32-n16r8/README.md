# ESP32-N16R8 Firmware

Place the compiled firmware files here for ESP32 boards with 16MB flash and 8MB PSRAM.

## Required Files
- `bootloader.bin`
- `partitions.bin`
- `boot_app0.bin`
- `firmware.bin`

## Arduino IDE Settings
- Board: "ESP32 Dev Module"
- Flash Size: "16MB (128Mb)"
- Flash Mode: "QIO"
- PSRAM: "Enabled"
- Partition Scheme: Choose one that fits 16MB flash

## Source Code
Compile `SOURCE_CODE/AccessControleESP32N16R8.ino`
