# ESP32 Firmware Web Flasher

Flash ESP32 boards directly from your browser - no Arduino IDE needed!

## 🚀 Quick Start

**Visit the web flasher:** https://btzll1412.github.io/access-control-addon/esp32-flasher/

1. Connect your ESP32 via USB
2. Click "INSTALL FIRMWARE"
3. Select your COM port
4. Wait for flashing to complete
5. Connect to WiFi: `AccessControl-Setup` (password: `12345678`)
6. Configure at http://192.168.4.1

## 📋 Requirements

- Google Chrome or Microsoft Edge browser
- ESP32 Dev Board (ESP32-WROOM-32 or compatible)
- USB cable
- CH340/CP2102 driver (usually auto-installs)

## 🔌 Hardware Wiring

See main repository README for complete wiring diagrams.

## 🛠️ Manual Flashing (Advanced)

If the web flasher doesn't work, you can use esptool.py:
```bash
esptool.py --chip esp32 --port COM3 --baud 921600 \
  --before default_reset --after hard_reset write_flash \
  -z --flash_mode dio --flash_freq 40m --flash_size 4MB \
  0x1000 bootloader.bin \
  0x8000 partitions.bin \
  0xe000 boot_app0.bin \
  0x10000 firmware.bin
```

## 📦 Files in this folder

- `index.html` - Web flasher interface
- `manifest.json` - Flash configuration
- `firmware.bin` - Main ESP32 firmware
- `bootloader.bin` - ESP32 bootloader
- `partitions.bin` - Partition table
- `boot_app0.bin` - Boot application

## 🔄 Updating Firmware

To update an existing board:
1. Visit the ESP32's web interface at http://[ESP32-IP]/
2. Go to /wifi-config to change settings
3. Or use the web flasher to completely reflash
```

4. Click **"Commit new file"**

### **Step 2: Upload the Binary Files**

1. Click into the `esp32-flasher` folder
2. Click **"Add file"** → **"Upload files"**
3. Drag and drop your 6 files:
   - ✅ `index.html`
   - ✅ `manifest.json`
   - ✅ `bootloader.bin`
   - ✅ `partitions.bin`
   - ✅ `boot_app0.bin`
   - ✅ `firmware.bin`
