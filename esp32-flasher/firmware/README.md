# Firmware Files

Each board type needs its own compiled firmware files. Place the compiled `.bin` files in the appropriate folder.

## Required Files Per Board

Each folder needs these 4 files:
- `bootloader.bin` - ESP32 bootloader
- `partitions.bin` - Partition table
- `boot_app0.bin` - Boot app (usually same for all)
- `firmware.bin` - Your compiled firmware

## Folder Structure

```
firmware/
├── esp32/              # Standard ESP32 (4MB flash)
│   ├── bootloader.bin
│   ├── partitions.bin
│   ├── boot_app0.bin
│   └── firmware.bin
│
├── esp32-n16r8/        # ESP32 with 16MB flash + 8MB PSRAM
│   ├── bootloader.bin
│   ├── partitions.bin
│   ├── boot_app0.bin
│   └── firmware.bin
│
└── esp32-s3/           # ESP32-S3 variant
    ├── bootloader.bin
    ├── partitions.bin
    ├── boot_app0.bin
    └── firmware.bin
```

## How to Compile

### Arduino IDE

1. Open the appropriate `.ino` file from `SOURCE_CODE/`:
   - `AccessControlESP32.ino` - For ESP32 Standard
   - `AccessControleESP32N16R8.ino` - For ESP32-N16R8

2. Select the correct board:
   - **ESP32 Standard**: "ESP32 Dev Module" with 4MB flash
   - **ESP32-N16R8**: "ESP32 Dev Module" with 16MB flash, QIO, 8MB PSRAM
   - **ESP32-S3**: "ESP32S3 Dev Module"

3. Go to Sketch → Export Compiled Binary

4. Find the exported files in the sketch folder and copy them here

### PlatformIO

1. Build with the appropriate environment
2. Find `.bin` files in `.pio/build/<env>/`
3. Copy the required files to the appropriate folder

## Notes

- The `boot_app0.bin` file is usually the same across all ESP32 variants
- Make sure partition tables match your flash size
- ESP32-S3 uses different bootloader offset (0x0 instead of 0x1000)
