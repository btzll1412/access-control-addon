# ESP32-S3 Firmware

Place the compiled firmware files here for ESP32-S3 boards.

## Required Files
- `bootloader.bin`
- `partitions.bin`
- `boot_app0.bin`
- `firmware.bin`

## Arduino IDE Settings
- Board: "ESP32S3 Dev Module"
- USB CDC On Boot: "Enabled" (if using USB for serial)
- Flash Size: Select appropriate size for your board
- PSRAM: "OPI PSRAM" if your board has it

## Note
ESP32-S3 requires a different source code adaptation.
The current source code may need modifications for S3 compatibility.
