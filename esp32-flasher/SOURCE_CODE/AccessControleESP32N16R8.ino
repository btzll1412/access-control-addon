/*
 * ===============================================================
 *  PROFESSIONAL ACCESS CONTROL SYSTEM - ESP32 FIRMWARE
 *  With Emergency Override, Real-Time Schedule & LIVE LOGS
 * ===============================================================
 */

#include <WiFi.h>
#include <WebServer.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <SPIFFS.h>
#include <Preferences.h>
#include <ESPmDNS.h>
#include <Update.h>
#include <esp_mac.h>  // For esp_read_mac() - reliable MAC address
#include <esp_task_wdt.h>  // Hardware watchdog
#include <esp_system.h>    // esp_reset_reason()

// Watchdog: force a chip reset if the fed task stops making progress for this long.
// Long enough to never false-trip on a normal (blocking) network call.
#define WDT_TIMEOUT_SECONDS 30

// ===============================================================
// VERSION & PSRAM SUPPORT
// ===============================================================
#define FIRMWARE_VERSION "3.2.3"

// PSRAM Allocator for large JSON documents
struct PSRAMAllocator {
    void* allocate(size_t size) {
        if (psramFound()) {
            return ps_malloc(size);
        }
        return malloc(size);
    }
    void deallocate(void* pointer) {
        free(pointer);
    }
    void* reallocate(void* ptr, size_t new_size) {
        if (psramFound()) {
            return ps_realloc(ptr, new_size);
        }
        return realloc(ptr, new_size);
    }
};
// ===============================================================
// CONFIGURATION
// ===============================================================

// GPIO Pin Definitions - ESP32-S3-DevKitC-1-N16R8
// NOTE: GPIO35, 36, 37 are reserved for PSRAM on N16R8!
#define WIEGAND_D0_DOOR1    4
#define WIEGAND_D1_DOOR1    5
#define WIEGAND_D0_DOOR2    6
#define WIEGAND_D1_DOOR2    7
#define RELAY_DOOR1         15
#define RELAY_DOOR2         16
#define REX_BUTTON_DOOR1    17
#define REX_BUTTON_DOOR2    18
#define LED_STATUS          38   // RGB LED on v1.1 boards (or 48 on v1.0)
#define BEEPER              8

// Reader LED and Beep Control
#define READER1_LED         9
#define READER1_BEEP        10
#define READER2_LED         11
#define READER2_BEEP        12

// ✅ EMERGENCY MODE CONSTANTS - MUST BE DEFINED FIRST!
#define EMERGENCY_NONE      0
#define EMERGENCY_LOCK      1
#define EMERGENCY_UNLOCK    2

// Default Settings
#define DEFAULT_UNLOCK_DURATION   3000
#define HEARTBEAT_INTERVAL        60000
#define LOG_QUEUE_MAX             500
// Inter-frame gap that marks the end of a Wiegand read. Kept at 100ms for
// reliability: on a marginal/noisy card signal a straggler bit can arrive late,
// and a shorter window risks cutting the frame early (-> wrong bit count). Only
// lower this once card reads are electrically clean.
#define WIEGAND_TIMEOUT           100
#define SCHEDULE_CHECK_INTERVAL   60000
#define READER_BEEP_SUCCESS_MS    100
#define READER_BEEP_ERROR_MS      500
#define READER_LED_SUCCESS_MS     2000
#define READER_LED_ERROR_MS       1000

// Live log buffer
#define LIVE_LOG_BUFFER_SIZE 200
String liveLogBuffer[LIVE_LOG_BUFFER_SIZE];
int liveLogIndex = 0;
unsigned long liveLogCounter = 0;
// Guards the live log buffer - addLiveLog() and getLiveLogsJSON() are called from
// both cores (Core 1 loop + Core 0 network task), so access must be serialized.
SemaphoreHandle_t liveLogMutex = NULL;

// WiFi Manager Settings
#define WIFI_PORTAL_TIMEOUT       300000

// Web Interface Credentials
#define WEB_USERNAME "admin"
#define WEB_PASSWORD "admin"

// ===============================================================
// GLOBAL OBJECTS
// ===============================================================

WebServer server(80);
Preferences preferences;
// NOTE: HTTPClient is NOT global. With the Core 0 network task, outbound HTTP can
// originate from two cores (networkTask, and web handlers that call
// announceToController on Core 1). A shared HTTPClient would corrupt; each sender
// uses its own local instance instead.

// ===============================================================
// STRUCTURES
// ===============================================================

struct WiegandData {
    volatile unsigned long lastBitTime = 0;
    volatile unsigned long value = 0;
    volatile int bitCount = 0;
    volatile bool dataReady = false;
    int d0Pin;
    int d1Pin;
};

struct ValidationResult {
    bool granted;
    String reason;
    String userName;
    bool isTempCode;
};

struct AccessLog {
    String timestamp;
    int doorNumber;
    String userName;
    String credential;
    String credentialType;
    bool granted;
    String reason;
};

struct TempCodeDoorUsage {
    String code;
    int doorNumber;
    int uses;
};

std::vector<TempCodeDoorUsage> tempCodeUsageTracker;

// ✅ FIXED: DoorConfig struct with proper emergencyOverride
struct DoorConfig {
    String name;
    String lastCredential;  // ✅ Add this if missing
    int relayPin;
    int rexPin;
    int readerLedPin;
    int readerBeepPin;
    WiegandData wiegand;
    bool isUnlocked;
    unsigned long unlockUntil;
    int unlockDuration;
    bool scheduledUnlock;
    String currentScheduleMode;
    String emergencyOverride;  // "lock", "unlock", or ""
};

struct BoardConfig {
    String boardName;
    String controllerIP;
    int controllerPort;
    String wifiSSID;
    String wifiPassword;
    bool configured;
    String macAddress;

    // Static IP configuration
    bool useStaticIP;      // true = static, false = DHCP
    String staticIP;       // Static IP address
    String gateway;        // Gateway address
    String subnet;         // Subnet mask
    String dns;            // DNS server

    // Emergency mode
    String emergencyMode;  // "lock", "unlock", or ""
    unsigned long emergencyAutoResetAt;  // millis() when to auto-reset
};

// ===============================================================
// GLOBAL VARIABLES
// ===============================================================

BoardConfig config;
DoorConfig doors[2];
std::vector<AccessLog> logQueue;

// ===============================================================
// DUAL-CORE: outbound network I/O runs on Core 0 so it never blocks the
// time-critical access path (Wiegand read -> validate -> relay) on Core 1.
// Door/relay control stays entirely on Core 1 to avoid cross-core relay races.
// logQueue is the hand-off point (Core 1 pushes, Core 0 drains) and is guarded
// by logQueueMutex.
// ===============================================================
TaskHandle_t networkTaskHandle = NULL;
SemaphoreHandle_t logQueueMutex = NULL;

// Push an access log for the Core 0 network task to send (thread-safe).
void enqueueAccessLog(const AccessLog& log) {
    if (logQueueMutex) xSemaphoreTake(logQueueMutex, portMAX_DELAY);
    if (logQueue.size() < LOG_QUEUE_MAX) {
        logQueue.push_back(log);
    } else {
        logQueue.erase(logQueue.begin());
        logQueue.push_back(log);
    }
    if (logQueueMutex) xSemaphoreGive(logQueueMutex);
}

// Thread-safe size read (the web status page on Core 1 reads this while the
// Core 0 network task may be erasing/inserting).
size_t logQueueSize() {
    size_t n = 0;
    if (logQueueMutex) xSemaphoreTake(logQueueMutex, portMAX_DELAY);
    n = logQueue.size();
    if (logQueueMutex) xSemaphoreGive(logQueueMutex);
    return n;
}



int door1UnlockDuration = 3000;
int door2UnlockDuration = 3000;

// Use PSRAM for large JSON documents (N16R8 has 8MB PSRAM)
// NOTE: usersDB must hold the ENTIRE sync payload (loadUsersDB re-parses the whole
// file), so it needs to be at least as large as the incoming sync document.
BasicJsonDocument<PSRAMAllocator> usersDB(262144);       // 256KB for users (was 64KB)
BasicJsonDocument<PSRAMAllocator> doorSchedulesDB(32768); // 32KB for schedules
BasicJsonDocument<PSRAMAllocator> tempCodesDB(32768);     // 32KB for temp codes
BasicJsonDocument<PSRAMAllocator> userSchedulesDB(32768); // 32KB for user schedules

unsigned long lastHeartbeat = 0;
unsigned long lastScheduleCheck = 0;
unsigned long lastEmergencyCheck = 0;
unsigned long lastKeypadTimeoutCheck = 0;
unsigned long lastLogRetry = 0;
bool controllerOnline = false;

String keypadBuffer = "";
unsigned long keypadLastKey = 0;
int currentKeypadDoor = -1;

unsigned long lastWiFiCheck = 0;
int wifiReconnectAttempts = 0;
bool apFallbackMode = false;  // True when broadcasting AP while trying to reconnect
String apFallbackSSID = "";   // AP SSID for fallback mode

// Non-blocking reader feedback timers
unsigned long readerLedOffTime[2] = {0, 0};
unsigned long readerBeepOffTime[2] = {0, 0};
bool readerBeepState[2] = {false, false};
int readerBeepCount[2] = {0, 0};
unsigned long readerBeepNextTime[2] = {0, 0};

// Non-blocking ONBOARD beeper (BEEPER pin) + status LED (LED_STATUS) state machines.
// Driven by checkOnboardFeedback() in loop() instead of delay().
int obBeepRemaining = 0;              // beeps left to play (including current)
bool obBeepOn = false;
unsigned long obBeepToggleAt = 0;
int obBeepOnMs = 100;
int obBeepOffMs = 80;

int obLedRemaining = 0;               // blinks left to play (including current)
bool obLedOn = false;
unsigned long obLedToggleAt = 0;
int obLedOnMs = 100;
int obLedOffMs = 100;

WiegandData* door1Wiegand = nullptr;
WiegandData* door2Wiegand = nullptr;

// ✅ ADD: beepPattern function declaration
void beepPattern(int count, int onTime, int offTime);
// Core 0 network task (defined after setup(), created inside setup()).
void networkTask(void* param);

// ===============================================================
// Helper functions for temp code tracking
// ===============================================================

int getTempCodeDoorUses(const String& code, int doorNumber) {
    for (const auto& usage : tempCodeUsageTracker) {
        if (usage.code == code && usage.doorNumber == doorNumber) {
            return usage.uses;
        }
    }
    return 0;
}

void incrementTempCodeDoorUses(const String& code, int doorNumber) {
    for (auto& usage : tempCodeUsageTracker) {
        if (usage.code == code && usage.doorNumber == doorNumber) {
            usage.uses++;
            return;
        }
    }
    
    TempCodeDoorUsage newUsage;
    newUsage.code = code;
    newUsage.doorNumber = doorNumber;
    newUsage.uses = 1;
    tempCodeUsageTracker.push_back(newUsage);
}

void clearTempCodeDoorUsage(const String& code) {
    tempCodeUsageTracker.erase(
        std::remove_if(tempCodeUsageTracker.begin(), tempCodeUsageTracker.end(),
            [&code](const TempCodeDoorUsage& usage) { return usage.code == code; }),
        tempCodeUsageTracker.end()
    );
}


// ===============================================================
// NEW: LIVE LOG FUNCTIONS
// ===============================================================

void addLiveLog(String message) {
    // Add timestamp
    String logEntry = getTimestamp() + " | " + message;

    // Add to circular buffer (serialized across cores)
    if (liveLogMutex) xSemaphoreTake(liveLogMutex, portMAX_DELAY);
    liveLogBuffer[liveLogIndex] = logEntry;
    liveLogIndex = (liveLogIndex + 1) % LIVE_LOG_BUFFER_SIZE;
    liveLogCounter++;
    if (liveLogMutex) xSemaphoreGive(liveLogMutex);

    // Also print to serial
    Serial.println(message);
}

String getLiveLogsJSON() {
    // ✅ OPTIMIZED: Direct string building, limit to 50 logs (was 200)
    // This prevents blocking the main loop when web page auto-refreshes
    String output = "{\"logs\":[";
    bool first = true;
    int count = 0;
    const int MAX_LOGS_TO_RETURN = 50;  // Reduced from 200

    if (liveLogMutex) xSemaphoreTake(liveLogMutex, portMAX_DELAY);
    for (int i = 0; i < LIVE_LOG_BUFFER_SIZE && count < MAX_LOGS_TO_RETURN; i++) {
        int idx = (liveLogIndex - 1 - i + LIVE_LOG_BUFFER_SIZE) % LIVE_LOG_BUFFER_SIZE;
        if (liveLogBuffer[idx].length() > 0) {
            if (!first) output += ",";
            output += "\"";
            // Escape quotes in log message
            String escaped = liveLogBuffer[idx];
            escaped.replace("\"", "\\\"");
            output += escaped;
            output += "\"";
            first = false;
            count++;
        }
    }
    unsigned long counterSnapshot = liveLogCounter;
    if (liveLogMutex) xSemaphoreGive(liveLogMutex);

    output += "],\"count\":";
    output += String(counterSnapshot);
    output += "}";

    return output;
}

// ===============================================================
// WIEGAND INTERRUPT HANDLERS
// ===============================================================

void IRAM_ATTR door1_D0_ISR() {
    if (door1Wiegand) {
        door1Wiegand->value <<= 1;
        door1Wiegand->bitCount++;
        door1Wiegand->lastBitTime = millis();
    }
}

void IRAM_ATTR door1_D1_ISR() {
    if (door1Wiegand) {
        door1Wiegand->value = (door1Wiegand->value << 1) | 1;
        door1Wiegand->bitCount++;
        door1Wiegand->lastBitTime = millis();
    }
}

void IRAM_ATTR door2_D0_ISR() {
    if (door2Wiegand) {
        door2Wiegand->value <<= 1;
        door2Wiegand->bitCount++;
        door2Wiegand->lastBitTime = millis();
    }
}

void IRAM_ATTR door2_D1_ISR() {
    if (door2Wiegand) {
        door2Wiegand->value = (door2Wiegand->value << 1) | 1;
        door2Wiegand->bitCount++;
        door2Wiegand->lastBitTime = millis();
    }
}


// ===============================================================
// ✅ NEW: READER BEEP & LED FUNCTIONS
// ===============================================================

// ===============================================================
// NON-BLOCKING READER BEEP & LED FUNCTIONS
// ===============================================================

void readerFeedbackSuccess(int doorNumber) {
    int idx = doorNumber - 1;
    
    // Turn on LED (will turn off after timeout)
    digitalWrite(doors[idx].readerLedPin, HIGH);
    readerLedOffTime[idx] = millis() + READER_LED_SUCCESS_MS;
    
    // Start beep pattern (2 short beeps)
    digitalWrite(doors[idx].readerBeepPin, HIGH);
    readerBeepState[idx] = true;
    readerBeepCount[idx] = 1;  // 1 more beep to do after this one
    readerBeepNextTime[idx] = millis() + READER_BEEP_SUCCESS_MS;
    readerBeepOffTime[idx] = millis() + READER_BEEP_SUCCESS_MS;
}

void readerFeedbackError(int doorNumber) {
    int idx = doorNumber - 1;
    
    // Turn on LED (will blink via checkReaderFeedback)
    digitalWrite(doors[idx].readerLedPin, HIGH);
    readerLedOffTime[idx] = millis() + READER_LED_ERROR_MS;
    
    // Single long beep for error
    digitalWrite(doors[idx].readerBeepPin, HIGH);
    readerBeepState[idx] = true;
    readerBeepCount[idx] = 0;  // No more beeps after this
    readerBeepOffTime[idx] = millis() + READER_BEEP_ERROR_MS;
    readerBeepNextTime[idx] = 0;
}

void checkReaderFeedback() {
    unsigned long now = millis();
    
    for (int i = 0; i < 2; i++) {
        // Check LED timeout
        if (readerLedOffTime[i] > 0 && now >= readerLedOffTime[i]) {
            digitalWrite(doors[i].readerLedPin, LOW);
            readerLedOffTime[i] = 0;
        }
        
        // Check beep timeout
        if (readerBeepOffTime[i] > 0 && now >= readerBeepOffTime[i]) {
            digitalWrite(doors[i].readerBeepPin, LOW);
            readerBeepState[i] = false;
            readerBeepOffTime[i] = 0;
            
            // Check if more beeps needed
            if (readerBeepCount[i] > 0 && readerBeepNextTime[i] > 0) {
                // Schedule next beep after short gap
                readerBeepNextTime[i] = now + 50;  // 50ms gap between beeps
            }
        }
        
        // Start next beep in pattern
        if (readerBeepNextTime[i] > 0 && now >= readerBeepNextTime[i] && !readerBeepState[i]) {
            if (readerBeepCount[i] > 0) {
                digitalWrite(doors[i].readerBeepPin, HIGH);
                readerBeepState[i] = true;
                readerBeepOffTime[i] = now + READER_BEEP_SUCCESS_MS;
                readerBeepCount[i]--;
                
                if (readerBeepCount[i] > 0) {
                    readerBeepNextTime[i] = now + READER_BEEP_SUCCESS_MS + 50;
                } else {
                    readerBeepNextTime[i] = 0;
                }
            } else {
                readerBeepNextTime[i] = 0;
            }
        }
    }
}

// ===============================================================
// UTILITY FUNCTIONS
// ===============================================================

// ---- Non-blocking primitives (state set here, played by checkOnboardFeedback) ----
void startBeepPattern(int count, int onMs, int offMs) {
    if (count <= 0) return;
    obBeepRemaining = count;
    obBeepOnMs = onMs;
    obBeepOffMs = offMs;
    obBeepOn = true;
    digitalWrite(BEEPER, HIGH);
    obBeepToggleAt = millis() + onMs;
}

void startBlink(int times, int onMs, int offMs) {
    if (times <= 0) return;
    obLedRemaining = times;
    obLedOnMs = onMs;
    obLedOffMs = offMs;
    obLedOn = true;
    digitalWrite(LED_STATUS, HIGH);
    obLedToggleAt = millis() + onMs;
}

void checkOnboardFeedback() {
    unsigned long now = millis();

    // Onboard beeper
    if (obBeepRemaining > 0 && now >= obBeepToggleAt) {
        if (obBeepOn) {
            digitalWrite(BEEPER, LOW);
            obBeepOn = false;
            obBeepRemaining--;
            if (obBeepRemaining > 0) obBeepToggleAt = now + obBeepOffMs;
        } else {
            digitalWrite(BEEPER, HIGH);
            obBeepOn = true;
            obBeepToggleAt = now + obBeepOnMs;
        }
    }

    // Onboard status LED
    if (obLedRemaining > 0 && now >= obLedToggleAt) {
        if (obLedOn) {
            digitalWrite(LED_STATUS, LOW);
            obLedOn = false;
            obLedRemaining--;
            if (obLedRemaining > 0) obLedToggleAt = now + obLedOffMs;
        } else {
            digitalWrite(LED_STATUS, HIGH);
            obLedOn = true;
            obLedToggleAt = now + obLedOnMs;
        }
    }
}

// ---- Same names as before, now non-blocking (no delay()) ----
void beep(int duration = 100) {
    startBeepPattern(1, duration, 80);
}

void beepSuccess() {
    startBeepPattern(2, 100, 80);
}

void beepError() {
    startBeepPattern(1, 500, 0);
}

void beepEmergency() {
    startBeepPattern(3, 200, 100);
}

void beepPattern(int count, int onTime, int offTime) {
    startBeepPattern(count, onTime, offTime);
}

// ===============================================================
// PIN VALIDATION (N16R8 PSRAM CONFLICT CHECK)
// ===============================================================

void validatePins() {
    addLiveLog("🔍 Validating pin assignments...");
    
    // Pins 35, 36, 37 are reserved for PSRAM on N16R8
    int reservedPins[] = {35, 36, 37};
    int usedPins[] = {
        WIEGAND_D0_DOOR1, WIEGAND_D1_DOOR1, 
        WIEGAND_D0_DOOR2, WIEGAND_D1_DOOR2, 
        RELAY_DOOR1, RELAY_DOOR2, 
        REX_BUTTON_DOOR1, REX_BUTTON_DOOR2, 
        LED_STATUS, BEEPER,
        READER1_LED, READER1_BEEP, 
        READER2_LED, READER2_BEEP
    };
    
    bool hasConflict = false;
    
    for (int r = 0; r < 3; r++) {
        for (int u = 0; u < 14; u++) {
            if (reservedPins[r] == usedPins[u]) {
                addLiveLog("🚨 CRITICAL: Pin " + String(reservedPins[r]) + " is reserved for PSRAM!");
                hasConflict = true;
            }
        }
    }
    
    if (!hasConflict) {
        addLiveLog("  ✅ All pins OK (no PSRAM conflicts)");
    }
}

void blinkLED(int times = 1) {
    startBlink(times, 100, 100);
}

String getTimestamp() {
    time_t now = time(nullptr);
    struct tm timeinfo;
    // 5ms (not 100ms): when NTP is synced getLocalTime returns instantly; when it
    // is NOT synced this is called on the swipe path (via addLiveLog) and a 100ms
    // block per log would add up. Fall back to millis() quickly instead.
    if (!getLocalTime(&timeinfo, 5)) {
        return String(millis()); // Fallback to millis if NTP not available
    }
    
    char buffer[30];
    strftime(buffer, sizeof(buffer), "%Y-%m-%d %H:%M:%S", &timeinfo);
    return String(buffer);
}

// ===============================================================
// CONFIGURATION MANAGEMENT
// ===============================================================

void loadConfig() {
    addLiveLog("📂 Loading configuration...");

    preferences.begin("access-ctrl", false);

    config.boardName = preferences.getString("boardName", "Unconfigured Board");
    config.controllerIP = preferences.getString("controllerIP", "");
    config.controllerPort = preferences.getInt("controllerPort", 8100);
    config.wifiSSID = preferences.getString("wifiSSID", "");
    config.wifiPassword = preferences.getString("wifiPass", "");
    config.configured = preferences.getBool("configured", false);

    // Static IP configuration (default to DHCP)
    config.useStaticIP = preferences.getBool("useStaticIP", false);
    config.staticIP = preferences.getString("staticIP", "");
    config.gateway = preferences.getString("gateway", "");
    config.subnet = preferences.getString("subnet", "255.255.255.0");
    config.dns = preferences.getString("dns", "8.8.8.8");

    // Emergency mode is NOT saved - always starts in normal mode
    config.emergencyMode = "";
    config.emergencyAutoResetAt = 0;

    doors[0].name = preferences.getString("door1Name", "Door 1");
    doors[0].unlockDuration = preferences.getInt("door1Unlock", DEFAULT_UNLOCK_DURATION);
    doors[0].emergencyOverride = "";
    doors[0].currentScheduleMode = "controlled";
    doors[0].scheduledUnlock = false;

    doors[1].name = preferences.getString("door2Name", "Door 2");
    doors[1].unlockDuration = preferences.getInt("door2Unlock", DEFAULT_UNLOCK_DURATION);
    doors[1].emergencyOverride = "";
    doors[1].currentScheduleMode = "controlled";
    doors[1].scheduledUnlock = false;

    preferences.end();

    addLiveLog("  Board: " + config.boardName);
    addLiveLog("  Controller: " + config.controllerIP + ":" + String(config.controllerPort));
    addLiveLog("  IP Mode: " + String(config.useStaticIP ? "Static" : "DHCP"));
    if (config.useStaticIP) {
        addLiveLog("  Static IP: " + config.staticIP);
    }
}

void saveConfig() {
    addLiveLog("💾 Saving configuration...");

    preferences.begin("access-ctrl", false);

    preferences.putString("boardName", config.boardName);
    preferences.putString("controllerIP", config.controllerIP);
    preferences.putInt("controllerPort", config.controllerPort);
    preferences.putString("wifiSSID", config.wifiSSID);
    preferences.putString("wifiPass", config.wifiPassword);
    preferences.putBool("configured", config.configured);

    // Static IP configuration
    preferences.putBool("useStaticIP", config.useStaticIP);
    preferences.putString("staticIP", config.staticIP);
    preferences.putString("gateway", config.gateway);
    preferences.putString("subnet", config.subnet);
    preferences.putString("dns", config.dns);

    preferences.putString("door1Name", doors[0].name);
    preferences.putInt("door1Unlock", doors[0].unlockDuration);

    preferences.putString("door2Name", doors[1].name);
    preferences.putInt("door2Unlock", doors[1].unlockDuration);

    preferences.end();

    addLiveLog("  ✅ Configuration saved");
}

bool loadUsersDB() {
    if (!SPIFFS.exists("/users.json")) {
        addLiveLog("⚠️  No user database found");
        return false;
    }
    
    File file = SPIFFS.open("/users.json", "r");
    if (!file) {
        addLiveLog("❌ Failed to open users database");
        return false;
    }
    
    DeserializationError error = deserializeJson(usersDB, file);
    file.close();
    
    if (error) {
        addLiveLog("❌ Failed to parse users database: " + String(error.c_str()));
        return false;
    }
    
    addLiveLog("✅ Users database loaded");
    if (usersDB.containsKey("users")) {
        addLiveLog("  Users: " + String(usersDB["users"].size()));
    }
    
    return true;
}

bool saveUsersDB(const String& jsonData) {
    File file = SPIFFS.open("/users.json", "w");
    if (!file) {
        addLiveLog("❌ Failed to save users database");
        return false;
    }
    
    file.print(jsonData);
    file.close();
    
    // Reload into memory
    return loadUsersDB();
}

// ===============================================================
// DOOR SCHEDULE FUNCTIONS
// ===============================================================

String checkDoorScheduleMode(int doorNumber) {
    String doorKey = String(doorNumber);
    
    if (!doorSchedulesDB.containsKey(doorKey)) {
        return "controlled";
    }
    
    time_t now = time(nullptr);
    struct tm timeinfo;
    if (!getLocalTime(&timeinfo, 100)) {
        return "controlled";
    }
    
    int currentDay = (timeinfo.tm_wday + 6) % 7;
    int currentHour = timeinfo.tm_hour;
    int currentMin = timeinfo.tm_min;
    int currentTimeMin = currentHour * 60 + currentMin;
    
    JsonArray schedules = doorSchedulesDB[doorKey];
    
    int highestPriority = -1;
    String mode = "controlled";
    
    for (JsonVariant schedule : schedules) {
        int scheduleDay = schedule["day"];
        if (scheduleDay != currentDay) continue;
        
        String startStr = schedule["start"].as<String>();
        int startHour = startStr.substring(0, 2).toInt();
        int startMin = startStr.substring(3, 5).toInt();
        int startTimeMin = startHour * 60 + startMin;
        
        String endStr = schedule["end"].as<String>();
        int endHour = endStr.substring(0, 2).toInt();
        int endMin = endStr.substring(3, 5).toInt();
        int endTimeMin = endHour * 60 + endMin;
        
        if (currentTimeMin >= startTimeMin && currentTimeMin < endTimeMin) {
            int priority = schedule.containsKey("priority") ? schedule["priority"].as<int>() : 0;
            
            if (priority > highestPriority) {
                mode = schedule["type"].as<String>();
                highestPriority = priority;
            }
        }
    }
    
    return mode;
}

void updateDoorModesFromSchedule() {
    addLiveLog("📅 Checking door schedules...");
    
    time_t now = time(nullptr);
    struct tm timeinfo;
    if (getLocalTime(&timeinfo, 100)) {
        addLiveLog("  Current time: " + String(timeinfo.tm_hour) + ":" + String(timeinfo.tm_min));
    }
    
    for (int i = 0; i < 2; i++) {
        int doorNumber = i + 1;
        
        if (doors[i].emergencyOverride != "") {
            addLiveLog("  Door " + String(doorNumber) + ": Emergency override active");
            continue;
        }
        
        if (config.emergencyMode != "") {
            addLiveLog("  Door " + String(doorNumber) + ": Board in emergency mode");
            continue;
        }
        
        String scheduledMode = checkDoorScheduleMode(doorNumber);
        doors[i].currentScheduleMode = scheduledMode;
        
        addLiveLog("  Door " + String(doorNumber) + " (" + doors[i].name + "): Mode = " + scheduledMode);
        
        if (scheduledMode == "unlock") {
            if (!doors[i].scheduledUnlock) {
                addLiveLog("    🔓 Unlocking door (schedule-based)");
                digitalWrite(doors[i].relayPin, HIGH);
                doors[i].isUnlocked = true;
                doors[i].scheduledUnlock = true;
                doors[i].unlockUntil = 0xFFFFFFFF;
                beepSuccess();
            }
        } else {
            if (doors[i].scheduledUnlock) {
                addLiveLog("    🔒 Locking door (schedule ended)");
                digitalWrite(doors[i].relayPin, LOW);
                doors[i].isUnlocked = false;
                doors[i].scheduledUnlock = false;
                doors[i].unlockUntil = 0;
                beep(200);
            }
        }
    }
}




// ===============================================================
// USER SCHEDULE VALIDATION
// ===============================================================

bool checkUserSchedule(const String& userName) {
    // If user schedules not loaded, allow access (default to 24/7)
    if (userSchedulesDB.isNull() || userSchedulesDB.size() == 0) {
        addLiveLog("  ℹ️  No user schedules loaded - allowing access");
        return true;
    }
    
    // Check if this user has any schedules
    if (!userSchedulesDB.containsKey(userName)) {
        addLiveLog("  ℹ️  User has no schedule restrictions (24/7)");
        return true;
    }
    
    // Get current time
    time_t now = time(nullptr);
    struct tm timeinfo;
    if (!getLocalTime(&timeinfo, 100)) {
        addLiveLog("  ⚠️  Could not get time - allowing access");
        return true;
    }
    
    int currentDay = (timeinfo.tm_wday + 6) % 7;  // Convert Sunday=0 to Sunday=6
    int currentHour = timeinfo.tm_hour;
    int currentMin = timeinfo.tm_min;
    int currentTimeMin = currentHour * 60 + currentMin;
    
    addLiveLog("  📅 Checking user schedule: Day=" + String(currentDay) + 
               ", Time=" + String(currentHour) + ":" + String(currentMin));
    
    // Check if current time matches any schedule entry
    JsonArray schedules = userSchedulesDB[userName];
    
    for (JsonVariant schedule : schedules) {
        int scheduleDay = schedule["day"];
        
        if (scheduleDay != currentDay) continue;
        
        String startStr = schedule["start"].as<String>();
        int startHour = startStr.substring(0, 2).toInt();
        int startMin = startStr.substring(3, 5).toInt();
        int startTimeMin = startHour * 60 + startMin;
        
        String endStr = schedule["end"].as<String>();
        int endHour = endStr.substring(0, 2).toInt();
        int endMin = endStr.substring(3, 5).toInt();
        int endTimeMin = endHour * 60 + endMin;
        
        // Check if current time is within this schedule
        if (currentTimeMin >= startTimeMin && currentTimeMin <= endTimeMin) {
            addLiveLog("  ✅ User within schedule: " + startStr + " - " + endStr);
            return true;
        }
    }
    
    // No matching schedule found
    addLiveLog("  ❌ User OUTSIDE schedule (Day=" + String(currentDay) + 
               ", Time=" + String(currentHour) + ":" + String(currentMin) + ")");
    return false;
}

// ===============================================================
// WIFI MANAGEMENT
// ===============================================================

void startWiFiManager() {
    addLiveLog("🔧 Starting WiFi Configuration Portal...");
    
    String apSSID = "AccessControl-" + String((uint32_t)ESP.getEfuseMac(), HEX);
    WiFi.softAP(apSSID.c_str(), "Config123");
    
    IPAddress IP = WiFi.softAPIP();
    addLiveLog("📡 WiFi Portal SSID: " + apSSID);
    addLiveLog("📡 Password: Config123");
    addLiveLog("🌐 Configure at: http://" + IP.toString());
    
    blinkLED(5);
    
    server.on("/", HTTP_GET, []() {
        String html = "<!DOCTYPE html><html><head><meta name='viewport' content='width=device-width, initial-scale=1'>";
        html += "<style>body{font-family:Arial;margin:40px;background:#f0f0f0}";
        html += ".container{background:white;padding:30px;border-radius:10px;max-width:500px;margin:auto}";
        html += "h1{color:#333}input,select{width:100%;padding:12px;margin:8px 0;border:1px solid #ddd;border-radius:5px;box-sizing:border-box}";
        html += "button{background:#4CAF50;color:white;padding:15px;border:none;border-radius:5px;cursor:pointer;width:100%;font-size:16px}";
        html += "button:hover{background:#45a049}";
        html += ".ip-section{background:#f9f9f9;padding:15px;border-radius:5px;margin:15px 0;display:none}";
        html += ".ip-section.show{display:block}";
        html += ".radio-group{margin:15px 0}";
        html += ".radio-group label{display:inline-block;margin-right:20px;cursor:pointer}";
        html += "</style>";
        html += "<script>";
        html += "function toggleIPSection(){";
        html += "  var isStatic=document.getElementById('ipStatic').checked;";
        html += "  document.getElementById('staticIPSection').className=isStatic?'ip-section show':'ip-section';";
        html += "}";
        html += "</script></head><body>";
        html += "<div class='container'><h1>🔐 Access Control Setup</h1>";
        html += "<form action='/save' method='POST'>";
        html += "<label>WiFi Network:</label><input name='ssid' required placeholder='Your WiFi SSID'>";
        html += "<label>WiFi Password:</label><input name='pass' type='password' required placeholder='WiFi Password'>";
        html += "<label>Board Name:</label><input name='board' required placeholder='e.g., Main Office'>";
        html += "<label>Controller IP:</label><input name='controller' placeholder='e.g., 192.168.1.100 (optional)'>";
        html += "<hr style='margin:20px 0'>";
        html += "<label style='font-weight:bold'>IP Configuration:</label>";
        html += "<div class='radio-group'>";
        html += "<label><input type='radio' name='ipMode' value='dhcp' id='ipDHCP' checked onclick='toggleIPSection()'> DHCP (Automatic)</label>";
        html += "<label><input type='radio' name='ipMode' value='static' id='ipStatic' onclick='toggleIPSection()'> Static IP</label>";
        html += "</div>";
        html += "<div id='staticIPSection' class='ip-section'>";
        html += "<label>Static IP Address:</label><input name='staticIP' placeholder='e.g., 192.168.1.50'>";
        html += "<label>Gateway:</label><input name='gateway' placeholder='e.g., 192.168.1.1'>";
        html += "<label>Subnet Mask:</label><input name='subnet' value='255.255.255.0' placeholder='255.255.255.0'>";
        html += "<label>DNS Server:</label><input name='dns' value='8.8.8.8' placeholder='8.8.8.8'>";
        html += "</div>";
        html += "<button type='submit'>💾 Save & Connect</button>";
        html += "</form></div></body></html>";

        server.send(200, "text/html", html);
    });

    server.on("/save", HTTP_POST, []() {
        config.wifiSSID = server.arg("ssid");
        config.wifiPassword = server.arg("pass");
        config.boardName = server.arg("board");
        config.controllerIP = server.arg("controller");
        config.configured = true;

        // Static IP configuration
        String ipMode = server.arg("ipMode");
        config.useStaticIP = (ipMode == "static");
        if (config.useStaticIP) {
            config.staticIP = server.arg("staticIP");
            config.gateway = server.arg("gateway");
            config.subnet = server.arg("subnet");
            config.dns = server.arg("dns");
            if (config.subnet.length() == 0) config.subnet = "255.255.255.0";
            if (config.dns.length() == 0) config.dns = "8.8.8.8";
        }

        saveConfig();
        
        String html = "<!DOCTYPE html><html><head><meta http-equiv='refresh' content='10;url=/'>";
        html += "<style>body{font-family:Arial;text-align:center;padding:50px;background:#f0f0f0}";
        html += ".success{background:white;padding:40px;border-radius:10px;max-width:400px;margin:auto}</style></head><body>";
        html += "<div class='success'><h1>✅ Configuration Saved!</h1>";
        html += "<p>Connecting to WiFi...</p><p>Board will restart in 10 seconds.</p></div></body></html>";
        
        server.send(200, "text/html", html);
        
        delay(3000);
        ESP.restart();
    });
    
    server.begin();
    
    unsigned long startTime = millis();
    while (millis() - startTime < WIFI_PORTAL_TIMEOUT) {
        server.handleClient();
        esp_task_wdt_reset();  // portal can run for minutes; keep watchdog fed
        delay(10);
    }

    addLiveLog("⏱️  WiFi Portal timeout - restarting...");
    ESP.restart();
}

// ===============================================================
// AP Fallback Mode - Non-blocking AP for WiFi recovery
// Broadcasts AP while continuing to try reconnecting to WiFi
// ===============================================================
void startAPFallbackMode() {
    if (apFallbackMode) {
        return;  // Already in fallback mode
    }

    addLiveLog("🚨 Starting AP Fallback Mode (WiFi recovery)");

    // Switch to AP+STA mode - this allows both AP and station to be active
    WiFi.mode(WIFI_AP_STA);

    // Create AP for configuration access. apFallbackSSID is built once at boot
    // and never reassigned, so the web status page on Core 1 can read it safely
    // while this runs on Core 0 (a String reassignment here would free the buffer
    // out from under a concurrent read).
    if (apFallbackSSID.length() == 0) {
        apFallbackSSID = "AccessControl-" + String((uint32_t)ESP.getEfuseMac(), HEX);
    }
    WiFi.softAP(apFallbackSSID.c_str(), "Config123");

    IPAddress apIP = WiFi.softAPIP();
    addLiveLog("📡 Fallback AP Started: " + apFallbackSSID);
    addLiveLog("📡 Password: Config123");
    addLiveLog("🌐 Configure at: http://" + apIP.toString());
    addLiveLog("⚠️  Will keep trying to reconnect to: " + config.wifiSSID);

    apFallbackMode = true;
    blinkLED(5);
}

void stopAPFallbackMode() {
    if (!apFallbackMode) {
        return;  // Not in fallback mode
    }

    addLiveLog("✅ Stopping AP Fallback Mode - WiFi reconnected!");

    // Turn off the AP
    WiFi.softAPdisconnect(true);

    // Switch back to STA only mode
    WiFi.mode(WIFI_STA);

    apFallbackMode = false;
    // NOTE: apFallbackSSID is intentionally NOT cleared - it is immutable after
    // boot so the Core 1 web handler can read it without a lock. It is only
    // displayed when apFallbackMode is true anyway.
}

bool connectWiFi() {
    if (config.wifiSSID.length() == 0) {
        addLiveLog("⚠️  No WiFi configured");
        return false;
    }

    addLiveLog("📡 Connecting to WiFi: " + config.wifiSSID);

    // Disconnect any previous connection first
    WiFi.disconnect(true);
    delay(100);

    WiFi.mode(WIFI_STA);

    // Apply static IP configuration if enabled
    if (config.useStaticIP && config.staticIP.length() > 0) {
        addLiveLog("🔧 Using Static IP: " + config.staticIP);

        IPAddress ip, gateway, subnet, dns;
        if (ip.fromString(config.staticIP) &&
            gateway.fromString(config.gateway) &&
            subnet.fromString(config.subnet) &&
            dns.fromString(config.dns)) {

            if (!WiFi.config(ip, gateway, subnet, dns)) {
                addLiveLog("⚠️  Static IP config failed, using DHCP");
            }
        } else {
            addLiveLog("⚠️  Invalid IP addresses, using DHCP");
        }
    } else {
        addLiveLog("🔧 Using DHCP");
    }

    WiFi.begin(config.wifiSSID.c_str(), config.wifiPassword.c_str());

    int attempts = 0;
    int maxAttempts = config.useStaticIP ? 20 : 30;  // Faster timeout for static IP

    while (WiFi.status() != WL_CONNECTED && attempts < maxAttempts) {
        delay(500);  // Reduced delay for faster connection
        esp_task_wdt_reset();  // keep watchdog fed during a slow connect (setup phase)
        Serial.print(".");
        if (attempts % 2 == 0) blinkLED(1);  // Blink less frequently
        attempts++;
    }

    if (WiFi.status() == WL_CONNECTED) {
        addLiveLog("✅ WiFi connected!");
        addLiveLog("📍 IP Address: " + WiFi.localIP().toString());

        config.macAddress = WiFi.macAddress();
        addLiveLog("🔖 MAC Address: " + config.macAddress);

        configTime(-5 * 3600, 3600, "pool.ntp.org", "time.nist.gov");

        return true;
    }

    addLiveLog("❌ WiFi connection failed after " + String(attempts) + " attempts");
    return false;
}

// ===============================================================
// CONTROLLER COMMUNICATION
// ===============================================================

bool announceToController() {
    if (config.controllerIP.length() == 0) {
        return false;
    }

    HTTPClient http;  // local instance (see note by WebServer decl)
    String url = "http://" + config.controllerIP + ":" + String(config.controllerPort) + "/api/board-announce";
    
    DynamicJsonDocument doc(512);
    doc["board_ip"] = WiFi.localIP().toString();
    doc["mac_address"] = config.macAddress;
    doc["board_name"] = config.boardName;
    doc["door1_name"] = doors[0].name;
    doc["door2_name"] = doors[1].name;
    
    String payload;
    serializeJson(doc, payload);
    
    addLiveLog("📢 Announcing to controller");
    
    http.begin(url);
    http.addHeader("Content-Type", "application/json");
    
    int httpCode = http.POST(payload);
    
    if (httpCode > 0) {
        addLiveLog("✅ Announced! Response: " + String(httpCode));
        http.end();
        return true;
    }
    
    addLiveLog("❌ Announcement failed: " + String(httpCode));
    http.end();
    return false;
}

bool sendHeartbeat() {
    if (config.controllerIP.length() == 0) return false;

    HTTPClient http;  // local instance (see note by WebServer decl)
    String url = "http://" + config.controllerIP + ":" + String(config.controllerPort) + "/api/heartbeat";

    DynamicJsonDocument doc(256);
    doc["ip_address"] = WiFi.localIP().toString();
    doc["board_name"] = config.boardName;

    String payload;
    serializeJson(doc, payload);

    http.begin(url);
    http.addHeader("Content-Type", "application/json");
    http.setTimeout(2000);  // 2 second timeout (reduced for non-blocking)
    
    int httpCode = http.POST(payload);
    http.end();
    
    bool online = (httpCode == 200);
    if (online != controllerOnline) {
        controllerOnline = online;
        addLiveLog(online ? "✅ Controller ONLINE" : "⚠️  Controller OFFLINE");
    }
    
    return online;
}

bool sendAccessLog(const AccessLog& log) {
    if (config.controllerIP.length() == 0) return false;

    HTTPClient http;  // local instance (see note by WebServer decl)
    String url = "http://" + config.controllerIP + ":" + String(config.controllerPort) + "/api/access-log";

    http.setConnectTimeout(2000);  // 2 second connection timeout (reduced for non-blocking)

    DynamicJsonDocument doc(512);
    doc["board_ip"] = WiFi.localIP().toString();
    doc["board_name"] = config.boardName;
    doc["door_number"] = log.doorNumber;
    doc["door_name"] = doors[log.doorNumber - 1].name;
    doc["user_name"] = log.userName;
    doc["credential"] = log.credential;
    doc["credential_type"] = log.credentialType;
    doc["access_granted"] = log.granted;
    doc["reason"] = log.reason;
    doc["timestamp"] = log.timestamp;

    String payload;
    serializeJson(doc, payload);

    http.begin(url);
    http.addHeader("Content-Type", "application/json");
    http.setTimeout(2000);  // 2 second timeout (reduced for non-blocking)

    int httpCode = http.POST(payload);
    
    if (httpCode == 200) {
        addLiveLog("✅ Log sent successfully");
        http.end();
        return true;
    } else {
        addLiveLog("❌ Log send failed: HTTP " + String(httpCode));
        if (httpCode > 0) {
            addLiveLog("   Response: " + http.getString());
        } else {
            addLiveLog("   Error: Connection failed or timeout");
        }
        http.end();
        return false;
    }
}

// Drains the log queue (runs on the Core 0 network task). Pops one entry under
// the mutex, then does the (blocking) HTTP send WITHOUT holding the lock so
// Core 1 can keep enqueuing. On failure the entry is put back and we stop.
//
// Capped at MAX_SENDS_PER_CALL: a large backlog (up to LOG_QUEUE_MAX=500) flushed
// back-to-back at ~60-100ms/send would otherwise run for tens of seconds without
// yielding, tripping the task watchdog. We also feed the WDT each iteration.
// Remaining entries are picked up on the next networkTask pass.
void sendQueuedLogs() {
    const int MAX_SENDS_PER_CALL = 20;
    int sent = 0;

    for (;;) {
        esp_task_wdt_reset();  // this runs on the WDT-subscribed networkTask

        if (sent >= MAX_SENDS_PER_CALL) break;  // yield; finish on the next pass

        AccessLog log;
        bool have = false;

        if (logQueueMutex) xSemaphoreTake(logQueueMutex, portMAX_DELAY);
        if (!logQueue.empty()) {
            log = logQueue.front();
            logQueue.erase(logQueue.begin());
            have = true;
        }
        if (logQueueMutex) xSemaphoreGive(logQueueMutex);

        if (!have) break;  // queue empty

        if (!sendAccessLog(log)) {
            // Send failed - put it back at the front and retry on the next pass.
            if (logQueueMutex) xSemaphoreTake(logQueueMutex, portMAX_DELAY);
            logQueue.insert(logQueue.begin(), log);
            if (logQueueMutex) xSemaphoreGive(logQueueMutex);
            break;
        }
        sent++;
    }
}

bool sendTempCodeUsage(const String& code, int currentUses) {
    if (config.controllerIP.length() == 0) return false;

    HTTPClient http;  // local instance (see note by WebServer decl)
    String url = "http://" + config.controllerIP + ":" + String(config.controllerPort) + "/api/temp-code-usage";
    
    DynamicJsonDocument doc(256);
    doc["code"] = code;
    doc["current_uses"] = currentUses;
    
    String payload;
    serializeJson(doc, payload);
    
    addLiveLog("🎫 Sending temp code usage update...");

    http.begin(url);
    http.addHeader("Content-Type", "application/json");
    http.setConnectTimeout(2000);
    http.setTimeout(2000);

    int httpCode = http.POST(payload);
    
    if (httpCode == 200) {
        addLiveLog("✅ Usage updated on server");
        http.end();
        return true;
    } else {
        addLiveLog("⚠️ Usage update failed: HTTP " + String(httpCode));
        http.end();
        return false;
    }
}

// ===============================================================
// EMERGENCY OVERRIDE FUNCTIONS
// ===============================================================

void checkEmergencyAutoReset() {
    if (config.emergencyMode == "unlock" && config.emergencyAutoResetAt > 0) {
        if (millis() >= config.emergencyAutoResetAt) {
            addLiveLog("⏰ Emergency unlock auto-reset triggered");
            
            config.emergencyMode = "";
            config.emergencyAutoResetAt = 0;
            
            digitalWrite(doors[0].relayPin, LOW);
            digitalWrite(doors[1].relayPin, LOW);
            doors[0].isUnlocked = false;
            doors[1].isUnlocked = false;
            
            beep(200);
            updateDoorModesFromSchedule();
        }
    }
}

String getEmergencyStatus() {

    if (config.emergencyMode == "lock") {
        return "🔴 EMERGENCY LOCKDOWN";
    } else if (config.emergencyMode == "unlock") {
        return "🟡 EMERGENCY EVACUATION";
    }
    return "🟢 Normal";
}

// ===============================================================
// ACCESS VALIDATION
// ===============================================================

ValidationResult validateAccess(int doorNumber, const String& credential, const String& credType) {
    ValidationResult result;
    result.granted = false;
    result.reason = "Unknown error";
    result.userName = "Unknown";
    result.isTempCode = false;  // ✅ Initialize to false
    
    // ===== EMERGENCY OVERRIDE CHECKS =====
    
    if (doors[doorNumber - 1].emergencyOverride == "lock") {
        result.reason = "Emergency lockdown (door-specific)";
        addLiveLog("  🚨 DENIED: Door in emergency lock mode");
        return result;
    }
    
    if (doors[doorNumber - 1].emergencyOverride == "unlock") {
        result.granted = true;
        result.reason = "Emergency unlock override (door-specific)";
        result.userName = "N/A (Emergency Override)";
        addLiveLog("  🚨 GRANTED: Door in emergency unlock mode");
        return result;
    }
    
    if (config.emergencyMode == "lock") {
        result.reason = "Emergency lockdown (board-wide)";
        addLiveLog("  🚨 DENIED: Board in emergency lock mode");
        return result;
    }
    
    if (config.emergencyMode == "unlock") {
        result.granted = true;
        result.reason = "Emergency unlock (board-wide evacuation)";
        result.userName = "N/A (Emergency Evacuation)";
        addLiveLog("  🚨 GRANTED: Board in emergency unlock mode");
        return result;
    }
    
    // ===== SCHEDULE MODE CHECKS =====
    
    String scheduleMode = doors[doorNumber - 1].currentScheduleMode;
    
    if (scheduleMode == "locked") {
        result.reason = "Door locked by schedule (lockdown period)";
        addLiveLog("  🔒 DENIED: Door in LOCKED schedule mode");
        return result;
    }
    
    if (scheduleMode == "unlock") {
        result.granted = true;
        result.reason = "Free access by schedule";
        result.userName = "Unknown";  // ✅ Default to Unknown
        
        // ✅ Try to identify user for logging purposes
        if (usersDB.containsKey("users")) {
            JsonArray users = usersDB["users"];
            for (JsonObject user : users) {
                bool credentialMatch = false;
                
                if (credType == "card") {
                    JsonArray cards = user["cards"];
                    for (JsonVariant card : cards) {
                        if (cardNumbersMatch(card.as<String>(), credential)) {
                            credentialMatch = true;
                            break;
                        }
                    }
                } else if (credType == "pin") {
                    JsonArray pins = user["pins"];
                    for (JsonVariant pin : pins) {
                        if (pin.as<String>() == credential) {
                            credentialMatch = true;
                            break;
                        }
                    }
                }

                if (credentialMatch) {
                    result.userName = user["name"].as<String>();
                    break;
                }
            }
        }
        
        // ✅ NEW: If still Unknown, check temp codes
        if (result.userName == "Unknown" && credType == "pin" && tempCodesDB.containsKey("temp_codes")) {
            JsonArray tempCodes = tempCodesDB["temp_codes"];
            for (JsonObject tempCode : tempCodes) {
                if (tempCode["code"].as<String>() == credential) {
                    result.userName = "🎫 " + tempCode["name"].as<String>();
                    break;
                }
            }
        }
        
        addLiveLog("  🔓 GRANTED: Door in UNLOCK schedule mode (User: " + result.userName + ")");
        return result;
    }
    
    // ===== CHECK REGULAR USERS =====

    if (usersDB.containsKey("users")) {
        JsonArray users = usersDB["users"];

        for (JsonObject user : users) {
            bool credentialMatch = false;

            if (credType == "card") {
                JsonArray cards = user["cards"];
                for (JsonVariant card : cards) {
                    if (cardNumbersMatch(card.as<String>(), credential)) {
                        credentialMatch = true;
                        break;
                    }
                }
            } else if (credType == "pin") {
                JsonArray pins = user["pins"];
                for (JsonVariant pin : pins) {
                    if (pin.as<String>() == credential) {
                        credentialMatch = true;
                        break;
                    }
                }
            }

            if (!credentialMatch) continue;

            result.userName = user["name"].as<String>();

            // Check if user is active FIRST
            if (!user["active"].as<bool>()) {
                result.reason = "User deactivated";
                addLiveLog("  ❌ User DEACTIVATED: " + result.userName);
                return result;
            }

            // Check door access
            JsonArray doors_access = user["doors"];
            bool hasDoorAccess = false;

            for (JsonVariant door : doors_access) {
                if (door.as<int>() == doorNumber) {
                    hasDoorAccess = true;
                    break;
                }
            }

            if (!hasDoorAccess) {
                result.reason = "No access to this door";
                addLiveLog("  ❌ User found but NO ACCESS to door " + String(doorNumber));
                return result;
            }

            // ✅ NEW: Check user schedule (time restrictions)
            if (!checkUserSchedule(result.userName)) {
                result.granted = false;
                result.reason = "Outside allowed schedule";
                addLiveLog("  ❌ User outside their allowed schedule");
                return result;
            }

            result.granted = true;
            result.reason = "Access granted";
            addLiveLog("  ✅ User validated: " + result.userName);
            return result;
        }
    }

    // ===== ✅ NEW: CHECK TEMP CODES =====

    if (credType == "pin" && tempCodesDB.containsKey("temp_codes")) {
        addLiveLog("  🎫 Checking temp codes...");
        
        JsonArray tempCodes = tempCodesDB["temp_codes"];
        
        for (JsonObject tempCode : tempCodes) {
            String code = tempCode["code"].as<String>();
            
            if (code != credential) continue;
            
            // Found matching temp code!
            String codeName = tempCode["name"].as<String>();
            result.userName = "🎫 " + codeName;  // ✅ Add emoji to match server
            
            addLiveLog("  🎫 Temp code matched: " + codeName);
            
            // Check if active
            if (!tempCode["active"].as<bool>()) {
                result.userName = "🎫 " + codeName;  
                result.isTempCode = true;             
                result.reason = "Temp code disabled";
                addLiveLog("  ❌ Temp code is DISABLED");
                return result;
            }
            
            // ===== CHECK 2: USAGE LIMITS (PER-DOOR) =====
            
            String usageType = tempCode["usage_type"].as<String>();
            int maxUses = tempCode["max_uses"] | 1;
            
            // ✅ NEW: Check usage for THIS SPECIFIC DOOR
            int doorUses = getTempCodeDoorUses(credential, doorNumber);
            
            if (usageType == "one_time" && doorUses >= 1) {
                result.userName = "🎫 " + codeName;  // ✅ ADD THIS
                result.isTempCode = true;             // ✅ ADD THIS
                result.reason = "Temp code already used on this door (one-time)";
                addLiveLog("  ❌ Temp code already used on Door " + String(doorNumber) + " (one-time)");
                return result;
            }
            
            if (usageType == "limited" && doorUses >= maxUses) {
                result.userName = "🎫 " + codeName;  // ✅ ADD THIS
                result.isTempCode = true;             // ✅ ADD THIS
                result.reason = "Temp code usage limit reached on this door";
                addLiveLog("  ❌ Temp code usage limit reached on Door " + String(doorNumber) + " (" + String(doorUses) + "/" + String(maxUses) + ")");
                return result;
            }
            
            addLiveLog("  ✅ Temp code usage OK on Door " + String(doorNumber) + " (" + String(doorUses) + "/" + String(maxUses) + " uses)");
            
            // Check door access
            JsonArray doors_access = tempCode["doors"];
            bool hasDoorAccess = false;
            
            for (JsonVariant door : doors_access) {
                if (door.as<int>() == doorNumber) {
                    hasDoorAccess = true;
                    break;
                }
            }
            
            if (!hasDoorAccess) {
                result.userName = "🎫 " + codeName;  // ✅ ADD THIS
                result.isTempCode = true;             // ✅ ADD THIS
                result.reason = "Temp code - no access to this door";
                addLiveLog("  ❌ Temp code NO ACCESS to door " + String(doorNumber));
                return result;
            }
            
            // ✅ ALL CHECKS PASSED - GRANT ACCESS!
            result.granted = true;
            result.reason = "Temp code access granted";
            result.userName = "🎫 " + codeName;  // ✅ Set temp code name
            result.isTempCode = true;  // ✅ Mark as temp code
            
            // ✅ NEW: Increment usage counter for THIS DOOR ONLY
            incrementTempCodeDoorUses(credential, doorNumber);

            // NOTE: We intentionally do NOT call sendTempCodeUsage() here. This
            // runs on the Core 1 access path and must not block on HTTP. The
            // server tracks usage authoritatively from the access-log that the
            // Core 0 network task sends for this same grant.

            // Get updated count (doorUses was already declared in CHECK 2 section above)
            int currentDoorUses = getTempCodeDoorUses(credential, doorNumber);
            addLiveLog("  ✅ Temp code GRANTED on Door " + String(doorNumber) + "! (Door uses: " + String(currentDoorUses) + ")");
            return result;  // ✅ ADDED: Must return after granting access!
        }
        
        addLiveLog("  🎫 No matching temp code found");
    }
    
    // ===== NO MATCH FOUND =====
    
    result.reason = "Unknown credential";
    addLiveLog("  ❌ Credential not found in users or temp codes");
    return result;
}
    


// ===============================================================
// DOOR CONTROL
// ===============================================================

void unlockDoor(int doorNumber) {
    if (doorNumber < 1 || doorNumber > 2) return;
    
    DoorConfig& door = doors[doorNumber - 1];
    
    if (door.scheduledUnlock) {
        addLiveLog("🔓 " + door.name + " already unlocked by schedule");
        beepSuccess();
        return;
    }
    
    addLiveLog("🔓 Unlocking " + door.name + " for " + String(door.unlockDuration) + "ms");
    
    digitalWrite(door.relayPin, HIGH);
    door.isUnlocked = true;
    door.unlockUntil = millis() + door.unlockDuration;
    
    beepSuccess();
    blinkLED(2);
}

void checkDoorLocks() {
    unsigned long now = millis();
    
    for (int i = 0; i < 2; i++) {
        if (doors[i].emergencyOverride == "lock" || doors[i].emergencyOverride == "unlock") {
            continue;
        }
        
        if (config.emergencyMode == "lock" || config.emergencyMode == "unlock") {
            continue;
        }
        
        if (doors[i].scheduledUnlock) {
            continue;
        }
        
        if (doors[i].isUnlocked && now >= doors[i].unlockUntil) {
            digitalWrite(doors[i].relayPin, LOW);
            doors[i].isUnlocked = false;
            addLiveLog("🔒 " + doors[i].name + " locked");
        }
    }
}

void processAccessAttempt(int doorNumber, const String& credential, const String& credType) {
    addLiveLog("🔐 Access attempt: Door " + String(doorNumber) + " | " + credType + " = " + credential);

    ValidationResult result = validateAccess(doorNumber, credential, credType);

    // ✅ Actuate the door FIRST - before any logging - so the relay fires as
    // fast as possible after the swipe. The addLiveLog() calls below each do a
    // (potentially blocking) Serial write, so doing them first would add ~15-30ms
    // of latency before the relay. Log AFTER the relay has already triggered.
    if (result.granted) {
        unlockDoor(doorNumber);
        readerFeedbackSuccess(doorNumber);
    } else {
        beepError();
        readerFeedbackError(doorNumber);
    }

    addLiveLog("  User: " + result.userName);
    addLiveLog("  Result: " + String(result.granted ? "✅ GRANTED" : "❌ DENIED"));
    addLiveLog("  Reason: " + result.reason);

    // ✅ THEN: Create the log and hand it to the Core 0 network task.
    // We do NOT send it here - this function runs on the time-critical Core 1
    // access path and must never block on network I/O. The network task drains
    // the queue and sends over HTTP.
    AccessLog log;
    log.timestamp = getTimestamp();
    log.doorNumber = doorNumber;
    log.userName = result.userName;
    log.credential = credential;
    log.credentialType = result.isTempCode ? "temp_code" : credType;
    log.granted = result.granted;
    log.reason = result.reason;

    enqueueAccessLog(log);
}

// ===============================================================
// WIEGAND PROCESSING (WITH RAW DATA LOGGING)
// ===============================================================

String parseWiegand26(unsigned long value) {
    uint8_t facilityCode = (value >> 17) & 0xFF;
    uint16_t cardNumber = (value >> 1) & 0xFFFF;

    return String(facilityCode) + " " + String(cardNumber);
}

// Normalize card number by stripping leading zeros from facility code
// e.g., "030 33993" -> "30 33993", "007 12345" -> "7 12345"
String normalizeCardNumber(const String& cardNum) {
    int spaceIdx = cardNum.indexOf(' ');
    if (spaceIdx <= 0) {
        // No space found, return as-is (card code only)
        return cardNum;
    }

    String facility = cardNum.substring(0, spaceIdx);
    String cardCode = cardNum.substring(spaceIdx + 1);

    // Strip leading zeros from facility code
    while (facility.length() > 1 && facility.startsWith("0")) {
        facility = facility.substring(1);
    }

    return facility + " " + cardCode;
}

// Check if two card numbers match (handles leading zeros in facility code)
bool cardNumbersMatch(const String& stored, const String& credential) {
    // Exact match first
    if (stored == credential) {
        return true;
    }

    // Try normalized match (strips leading zeros from facility code)
    // e.g., stored "030 33993" matches credential "30 33993"
    if (normalizeCardNumber(stored) == normalizeCardNumber(credential)) {
        return true;
    }

    // If credential has space (facility + code), try matching just the card code
    // This supports cards stored as just the card code (last 5 digits)
    if (credential.indexOf(' ') > 0) {
        String cardCodeOnly = credential.substring(credential.indexOf(' ') + 1);
        if (stored == cardCodeOnly) {
            return true;
        }
    }

    return false;
}

void processWiegandData(int doorNumber, WiegandData& wiegand) {
    // ===============================================================
    // RAW WIEGAND DATA LOGGING
    // ===============================================================
    
    String rawLog = "🔍 RAW WIEGAND - Door " + String(doorNumber) + ": ";
    rawLog += "Bits=" + String(wiegand.bitCount) + " | ";
    rawLog += "DEC=" + String(wiegand.value) + " | ";
    rawLog += "HEX=0x" + String(wiegand.value, HEX) + " | ";
    rawLog += "BIN=";
    
    // Binary representation
    for (int i = wiegand.bitCount - 1; i >= 0; i--) {
        rawLog += ((wiegand.value >> i) & 1) ? "1" : "0";
        if (i % 4 == 0 && i > 0) rawLog += " ";
    }
    
    addLiveLog(rawLog);
    
    // ===============================================================
    // Process based on bit count
    // ===============================================================
    
    if (wiegand.bitCount == 26) {
        // Full card scan
        String cardNumber = parseWiegand26(wiegand.value);
        uint8_t facilityCode = (wiegand.value >> 17) & 0xFF;
        uint16_t cardNum = (wiegand.value >> 1) & 0xFFFF;
        
        addLiveLog("💳 Card: Facility=" + String(facilityCode) + ", Number=" + String(cardNum));
        
        doors[doorNumber - 1].lastCredential = cardNumber;
        processAccessAttempt(doorNumber, cardNumber, "card");
        
    } else if (wiegand.bitCount == 4 || wiegand.bitCount == 8) {
        // Keypad key press
        uint8_t keyValue = wiegand.value & 0x0F;
        char key;
        
        // Convert to actual key
        if (keyValue <= 9) {
            key = '0' + keyValue;
        } else if (keyValue == 10) {
            key = '*';
        } else if (keyValue == 11) {
            key = '#';
        } else {
            key = '?';
        }
        
        addLiveLog("🔢 Keypad: Key '" + String(key) + "' (value=" + String(keyValue) + ")");
        
        // Handle keypad input
        if (key == '#') {
            // End of PIN entry
            if (keypadBuffer.length() >= 4 && currentKeypadDoor == doorNumber) {
                addLiveLog("🔢 PIN complete: " + String(keypadBuffer.length()) + " digits ****");
                processAccessAttempt(doorNumber, keypadBuffer, "pin");
            } else {
                addLiveLog("⚠️  PIN too short (" + String(keypadBuffer.length()) + " digits) or wrong door");
            }
            keypadBuffer = "";
            currentKeypadDoor = -1;
            keypadLastKey = 0;  // Reset timer
            
        } else if (key == '*') {
            // Clear buffer
            addLiveLog("🔢 PIN buffer cleared");
            keypadBuffer = "";
            currentKeypadDoor = -1;
            keypadLastKey = 0;  // Reset timer
            
        } else {
            // Add digit to buffer
            if (currentKeypadDoor != doorNumber) {
                keypadBuffer = "";
                currentKeypadDoor = doorNumber;
            }
            
            keypadBuffer += key;
            keypadLastKey = millis();  // ✅ Update timer AFTER adding digit
            
            addLiveLog("🔢 PIN buffer: " + String(keypadBuffer.length()) + " digits");
            
            if (keypadBuffer.length() > 8) {
                addLiveLog("⚠️  PIN too long - clearing");
                keypadBuffer = "";
                currentKeypadDoor = -1;
                keypadLastKey = 0;
            }
        }
    } else {
        addLiveLog("⚠️  Unknown bit count: " + String(wiegand.bitCount));
    }
    
    // Reset wiegand data
    wiegand.value = 0;
    wiegand.bitCount = 0;
    wiegand.dataReady = false;
}

void checkWiegandData() {
    unsigned long now = millis();
    
    // ===============================================================
    // Check Wiegand data
    // ===============================================================
    
    // Check Door 1 Wiegand
    if (doors[0].wiegand.bitCount > 0 && 
        (now - doors[0].wiegand.lastBitTime) > WIEGAND_TIMEOUT) {
        doors[0].wiegand.dataReady = true;
    }
    
    if (doors[0].wiegand.dataReady) {
        processWiegandData(1, doors[0].wiegand);
    }
    
    // Check Door 2 Wiegand
    if (doors[1].wiegand.bitCount > 0 && 
        (now - doors[1].wiegand.lastBitTime) > WIEGAND_TIMEOUT) {
        doors[1].wiegand.dataReady = true;
    }
    
    if (doors[1].wiegand.dataReady) {
        processWiegandData(2, doors[1].wiegand);
    }
    
    // ===============================================================
    // ✅ KEYPAD TIMEOUT - Only check every 5 seconds!
    // ===============================================================
    
    if (now - lastKeypadTimeoutCheck >= 5000) {  // Only check every 5 seconds
        lastKeypadTimeoutCheck = now;
        
        if (keypadBuffer.length() > 0 && keypadLastKey > 1000) {
            unsigned long timeSinceLastKey = now - keypadLastKey;
            
            // 30 second timeout for incomplete PINs
            if (timeSinceLastKey > 30000) {
                addLiveLog("⏱️  Keypad timeout after " + String(timeSinceLastKey / 1000) + " seconds");
                keypadBuffer = "";
                currentKeypadDoor = -1;
                keypadLastKey = 0;
            }
        }
    }
}

// ===============================================================
// WEB INTERFACE
// ===============================================================

bool checkAuth() {
    if (!server.authenticate(WEB_USERNAME, WEB_PASSWORD)) {
        server.requestAuthentication();
        return false;
    }
    return true;
}

void setupWebInterface() {
    // Main page with Live Logs tab
    server.on("/", HTTP_GET, []() {
        if (!checkAuth()) return;
        
        String emergencyStatus = getEmergencyStatus();
        String emergencyColor = "#10b981";
        if (config.emergencyMode == "lock") emergencyColor = "#ef4444";
        if (config.emergencyMode == "unlock") emergencyColor = "#f59e0b";
        
        String html = "<!DOCTYPE html><html><head><meta name='viewport' content='width=device-width, initial-scale=1'>";
        html += "<style>";
        html += "body{font-family:Arial;margin:0;padding:0;background:#f0f0f0}";
        html += ".container{max-width:1200px;margin:auto;padding:20px}";
        html += "h1{color:#333;border-bottom:3px solid #4CAF50;padding-bottom:10px}";
        html += ".emergency-banner{background:" + emergencyColor + ";color:white;padding:15px;border-radius:8px;margin-bottom:20px;text-align:center;font-weight:bold;font-size:18px}";
        html += ".tabs{display:flex;background:#fff;border-radius:8px 8px 0 0;overflow:hidden;margin-top:20px}";
        html += ".tab{flex:1;padding:15px;text-align:center;cursor:pointer;background:#f9f9f9;border:none;font-size:16px;font-weight:bold;transition:all 0.3s}";
        html += ".tab:hover{background:#e0e0e0}";
        html += ".tab.active{background:#4CAF50;color:white}";
        html += ".tab-content{display:none;background:white;padding:30px;border-radius:0 0 8px 8px}";
        html += ".tab-content.active{display:block}";
        html += ".status{padding:10px;margin:10px 0;border-radius:5px}";
        html += ".online{background:#d4edda;color:#155724}";
        html += ".offline{background:#f8d7da;color:#721c24}";
        html += "table{width:100%;border-collapse:collapse;margin:10px 0}";
        html += "td{padding:8px;border-bottom:1px solid #ddd}";
        html += "button{background:#4CAF50;color:white;padding:12px 20px;border:none;border-radius:5px;cursor:pointer;margin:5px}";
        html += "button:hover{background:#45a049}";
        
        // Live logs styling
        html += ".log-container{background:#1e1e1e;color:#00ff00;padding:20px;border-radius:8px;font-family:'Courier New',monospace;font-size:13px;max-height:600px;overflow-y:auto}";
        html += ".log-entry{padding:5px 0;border-bottom:1px solid #333;line-height:1.6}";
        html += ".log-timestamp{color:#888;margin-right:10px}";
        html += ".log-controls{margin-bottom:15px;text-align:right}";
        html += ".log-controls button{background:#333;color:#00ff00;border:1px solid #00ff00}";
        html += ".log-controls button:hover{background:#00ff00;color:#000}";
        html += "</style>";
        
        // JavaScript for tabs and auto-refresh logs
        html += "<script>";
        html += "function showTab(tabName){";
        html += "  var tabs=document.getElementsByClassName('tab-content');";
        html += "  for(var i=0;i<tabs.length;i++){tabs[i].classList.remove('active');}";
        html += "  var btns=document.getElementsByClassName('tab');";
        html += "  for(var i=0;i<btns.length;i++){btns[i].classList.remove('active');}";
        html += "  document.getElementById(tabName).classList.add('active');";
        html += "  event.target.classList.add('active');";
        html += "  if(tabName=='logs'){startLogRefresh();}else{stopLogRefresh();}";
        html += "}";
        
        // Auto-refresh logs
        html += "var logRefreshInterval;";
        html += "function startLogRefresh(){";
        html += "  refreshLogs();";
        html += "  logRefreshInterval=setInterval(refreshLogs,2000);";
        html += "}";
        html += "function stopLogRefresh(){";
        html += "  if(logRefreshInterval)clearInterval(logRefreshInterval);";
        html += "}";
        html += "function refreshLogs(){";
        html += "  fetch('/api/logs').then(r=>r.json()).then(data=>{";
        html += "    var html='';";
        html += "    data.logs.forEach(log=>{";
        html += "      var parts=log.split(' | ');";
        html += "      html+='<div class=\"log-entry\">';";
        html += "      html+='<span class=\"log-timestamp\">'+parts[0]+'</span>';";
        html += "      html+='<span>'+(parts[1]||log)+'</span>';";
        html += "      html+='</div>';";
        html += "    });";
        html += "    document.getElementById('log-entries').innerHTML=html;";
        html += "    document.getElementById('log-count').innerText='('+data.count+' total)';";
        html += "  });";
        html += "}";
        html += "function clearLogs(){";
        html += "  if(confirm('Clear all logs?')){";
        html += "    fetch('/api/logs/clear',{method:'POST'}).then(()=>refreshLogs());";
        html += "  }";
        html += "}";
        html += "</script>";
        
        html += "</head><body>";
        html += "<div class='container'>";
        html += "<h1>🔐 Access Control Board</h1>";
        
        if (config.emergencyMode != "") {
            html += "<div class='emergency-banner'>" + emergencyStatus + "</div>";
        }
        
        // Tabs
        html += "<div class='tabs'>";
        html += "<button class='tab active' onclick='showTab(\"status\")'>📊 Status</button>";
        html += "<button class='tab' onclick='showTab(\"doors\")'>🚪 Doors</button>";
        html += "<button class='tab' onclick='showTab(\"logs\")'>📋 Live Logs</button>";
        html += "<button class='tab' onclick='showTab(\"config\")'>⚙️ Config</button>";
        html += "</div>";
        
        // Status Tab
        html += "<div id='status' class='tab-content active'>";
        html += "<h2>System Status</h2>";
        html += "<div class='status " + String(WiFi.status() == WL_CONNECTED ? "online" : "offline") + "'>";
        html += "WiFi: " + String(WiFi.status() == WL_CONNECTED ? "✅ Connected" : "❌ Disconnected");
        html += "</div>";
        html += "<div class='status " + String(controllerOnline ? "online" : "offline") + "'>";
        html += "Controller: " + String(controllerOnline ? "✅ Online" : "⚠️ Offline");
        html += "</div>";
        if (apFallbackMode) {
            html += "<div class='status' style='background:#fff3cd;color:#856404'>";
            html += "📡 AP Fallback Mode Active - SSID: " + apFallbackSSID;
            html += "</div>";
        }
        html += "<table>";
        html += "<tr><td><b>Board Name:</b></td><td>" + config.boardName + "</td></tr>";
        html += "<tr><td><b>IP Address:</b></td><td>" + WiFi.localIP().toString() + "</td></tr>";
        html += "<tr><td><b>MAC Address:</b></td><td>" + config.macAddress + "</td></tr>";
        html += "<tr><td><b>Controller IP:</b></td><td>" + (config.controllerIP.length() > 0 ? config.controllerIP : "Not configured") + "</td></tr>";
        html += "<tr><td><b>Users Loaded:</b></td><td>" + String(usersDB.containsKey("users") ? usersDB["users"].size() : 0) + "</td></tr>";
        html += "<tr><td><b>Queued Logs:</b></td><td>" + String(logQueueSize()) + "/" + String(LOG_QUEUE_MAX) + "</td></tr>";
        html += "<tr><td><b>Emergency Mode:</b></td><td style='color:" + emergencyColor + "'><b>" + emergencyStatus + "</b></td></tr>";
        html += "<tr><td><b>Free Heap:</b></td><td>" + String(ESP.getFreeHeap() / 1024) + " KB</td></tr>";
        if (psramFound()) {
            html += "<tr><td><b>Free PSRAM:</b></td><td>" + String(ESP.getFreePsram() / 1024) + " KB</td></tr>";
        }
        html += "<tr><td><b>Firmware:</b></td><td>v" + String(FIRMWARE_VERSION) + "</td></tr>";
        html += "</table>";
        html += "</div>";
        
        // Doors Tab
        html += "<div id='doors' class='tab-content'>";
        html += "<h2>🚪 Door Control</h2>";
        html += "<table>";
        for (int i = 0; i < 2; i++) {
            String doorStatus = doors[i].isUnlocked ? "🔓 Unlocked" : "🔒 Locked";
            if (doors[i].emergencyOverride == "lock") doorStatus = "🚨 EMERGENCY LOCKED";
            if (doors[i].emergencyOverride == "unlock") doorStatus = "🚨 EMERGENCY UNLOCKED";
            if (doors[i].scheduledUnlock) doorStatus += " (by schedule)";
            
            String scheduleMode = doors[i].currentScheduleMode;
            String scheduleText = "";
            if (scheduleMode == "unlock") scheduleText = " [Schedule: FREE ACCESS]";
            else if (scheduleMode == "locked") scheduleText = " [Schedule: LOCKDOWN]";
            else if (scheduleMode == "controlled") scheduleText = " [Schedule: CONTROLLED]";
            
            html += "<tr><td><b>" + doors[i].name + ":</b></td><td>";
            html += doorStatus + scheduleText;
            html += "</td><td><button onclick=\"location.href='/unlock?door=" + String(i + 1) + "'\">🔓 Unlock</button></td></tr>";
        }
        html += "</table>";
        html += "</div>";
        
        // Live Logs Tab
        html += "<div id='logs' class='tab-content'>";
        html += "<h2>📋 Live System Logs <span id='log-count'></span></h2>";
        html += "<div class='log-controls'>";
        html += "<button onclick='refreshLogs()'>🔄 Refresh</button>";
        html += "<button onclick='clearLogs()'>🗑️ Clear</button>";
        html += "</div>";
        html += "<div class='log-container'>";
        html += "<div id='log-entries'>Loading logs...</div>";
        html += "</div>";
        html += "<p style='color:#888;font-size:12px;margin-top:10px'>Auto-refreshes every 2 seconds. Shows raw Wiegand data including individual keypad presses.</p>";
        html += "</div>";
        
        // Config Tab
        html += "<div id='config' class='tab-content'>";
        html += "<h2>⚙️ Configuration</h2>";
        html += "<button onclick=\"location.href='/config'\">Edit Configuration</button>";
        html += "<button onclick=\"location.href='/update'\" style='background:#3b82f6'>🔄 Firmware Update (OTA)</button>";
        html += "<button onclick=\"if(confirm('Restart board?'))location.href='/restart'\" style='background:#f44336'>Restart Board</button>";
        html += "</div>";
        
        html += "</div>";
        html += "</body></html>";
        
        server.send(200, "text/html", html);
    });
    
    // API: Get logs as JSON
    server.on("/api/logs", HTTP_GET, []() {
        server.send(200, "application/json", getLiveLogsJSON());
    });
    
    // API: Clear logs
    server.on("/api/logs/clear", HTTP_POST, []() {
        for (int i = 0; i < LIVE_LOG_BUFFER_SIZE; i++) {
            liveLogBuffer[i] = "";
        }
        liveLogIndex = 0;
        addLiveLog("🗑️ Logs cleared by user");
        server.send(200, "application/json", "{\"success\":true}");
    });
    
    // Configuration page
    server.on("/config", HTTP_GET, []() {
        if (!checkAuth()) return;

        String dhcpChecked = config.useStaticIP ? "" : "checked";
        String staticChecked = config.useStaticIP ? "checked" : "";
        String staticDisplay = config.useStaticIP ? "block" : "none";

        String html = "<!DOCTYPE html><html><head><meta name='viewport' content='width=device-width, initial-scale=1'>";
        html += "<style>body{font-family:Arial;margin:20px;background:#f0f0f0}";
        html += ".container{background:white;padding:30px;border-radius:10px;max-width:600px;margin:auto}";
        html += "h1{color:#333}input{width:100%;padding:12px;margin:8px 0;border:1px solid #ddd;border-radius:5px;box-sizing:border-box}";
        html += "button{background:#4CAF50;color:white;padding:15px;border:none;border-radius:5px;cursor:pointer;width:100%;font-size:16px}";
        html += "button:hover{background:#45a049}label{font-weight:bold}";
        html += ".section{background:#f9f9f9;padding:15px;border-radius:5px;margin:15px 0}";
        html += ".section h3{margin-top:0;color:#666}";
        html += ".radio-group{margin:10px 0}";
        html += ".radio-group label{display:inline-block;margin-right:20px;font-weight:normal;cursor:pointer}";
        html += "#staticIPSection{display:" + staticDisplay + "}";
        html += ".info{background:#e3f2fd;padding:10px;border-radius:5px;margin:10px 0;font-size:13px;color:#1565c0}";
        html += "</style>";
        html += "<script>";
        html += "function toggleIPSection(){";
        html += "  var isStatic=document.getElementById('ipStatic').checked;";
        html += "  document.getElementById('staticIPSection').style.display=isStatic?'block':'none';";
        html += "}";
        html += "</script></head><body>";
        html += "<div class='container'><h1>⚙️ Board Configuration</h1>";
        html += "<form action='/save-config' method='POST'>";
        html += "<label>Board Name:</label><input name='boardName' value='" + config.boardName + "' required>";
        html += "<label>Controller IP:</label><input name='controllerIP' value='" + config.controllerIP + "' placeholder='192.168.1.100'>";
        html += "<label>Controller Port:</label><input name='controllerPort' type='number' value='" + String(config.controllerPort) + "'>";

        // Door settings
        html += "<div class='section'><h3>Door Settings</h3>";
        html += "<label>Door 1 Name:</label><input name='door1Name' value='" + doors[0].name + "'>";
        html += "<label>Door 1 Unlock (ms):</label><input name='door1Unlock' type='number' value='" + String(doors[0].unlockDuration) + "'>";
        html += "<label>Door 2 Name:</label><input name='door2Name' value='" + doors[1].name + "'>";
        html += "<label>Door 2 Unlock (ms):</label><input name='door2Unlock' type='number' value='" + String(doors[1].unlockDuration) + "'>";
        html += "</div>";

        // Network settings
        html += "<div class='section'><h3>Network Settings</h3>";
        html += "<label>IP Configuration:</label>";
        html += "<div class='radio-group'>";
        html += "<label><input type='radio' name='ipMode' value='dhcp' id='ipDHCP' " + dhcpChecked + " onclick='toggleIPSection()'> DHCP (Automatic)</label>";
        html += "<label><input type='radio' name='ipMode' value='static' id='ipStatic' " + staticChecked + " onclick='toggleIPSection()'> Static IP</label>";
        html += "</div>";
        html += "<div id='staticIPSection'>";
        html += "<label>Static IP Address:</label><input name='staticIP' value='" + config.staticIP + "' placeholder='e.g., 192.168.1.50'>";
        html += "<label>Gateway:</label><input name='gateway' value='" + config.gateway + "' placeholder='e.g., 192.168.1.1'>";
        html += "<label>Subnet Mask:</label><input name='subnet' value='" + (config.subnet.length() > 0 ? config.subnet : "255.255.255.0") + "'>";
        html += "<label>DNS Server:</label><input name='dns' value='" + (config.dns.length() > 0 ? config.dns : "8.8.8.8") + "'>";
        html += "</div>";
        html += "<div class='info'>Current IP: " + WiFi.localIP().toString() + " | MAC: " + config.macAddress + "</div>";
        html += "</div>";

        html += "<button type='submit'>💾 Save Configuration</button>";
        html += "</form>";
        html += "<br><button onclick=\"location.href='/'\">← Back</button>";
        html += "<button onclick=\"if(confirm('Reset WiFi settings and restart in AP mode?'))location.href='/reset-wifi'\" style='background:#f44336;margin-top:10px'>Reset WiFi Settings</button>";
        html += "</div></body></html>";

        server.send(200, "text/html", html);
    });
    
    // Save configuration
    server.on("/save-config", HTTP_POST, []() {
        if (!checkAuth()) return;

        config.boardName = server.arg("boardName");
        config.controllerIP = server.arg("controllerIP");
        config.controllerPort = server.arg("controllerPort").toInt();

        doors[0].name = server.arg("door1Name");
        doors[0].unlockDuration = server.arg("door1Unlock").toInt();

        doors[1].name = server.arg("door2Name");
        doors[1].unlockDuration = server.arg("door2Unlock").toInt();

        // Static IP configuration
        String ipMode = server.arg("ipMode");
        bool previousStaticIP = config.useStaticIP;
        String previousIP = config.staticIP;

        config.useStaticIP = (ipMode == "static");
        if (config.useStaticIP) {
            config.staticIP = server.arg("staticIP");
            config.gateway = server.arg("gateway");
            config.subnet = server.arg("subnet");
            config.dns = server.arg("dns");
            if (config.subnet.length() == 0) config.subnet = "255.255.255.0";
            if (config.dns.length() == 0) config.dns = "8.8.8.8";
        }

        saveConfig();

        // Check if network settings changed (requires restart)
        bool networkChanged = (previousStaticIP != config.useStaticIP) ||
                              (config.useStaticIP && previousIP != config.staticIP);

        String html = "<!DOCTYPE html><html><head>";
        if (networkChanged) {
            html += "<meta http-equiv='refresh' content='10;url=/'>";
        } else {
            html += "<meta http-equiv='refresh' content='3;url=/'>";
        }
        html += "</head><body style='text-align:center;padding:50px;font-family:Arial'>";
        html += "<h1>✅ Configuration Saved!</h1>";
        if (networkChanged) {
            html += "<p>Network settings changed. Board will restart...</p>";
        } else {
            html += "<p>Redirecting...</p>";
        }
        html += "</body></html>";

        server.send(200, "text/html", html);

        if (config.controllerIP.length() > 0) {
            delay(1000);
            announceToController();
        }

        // Restart if network settings changed
        if (networkChanged) {
            delay(2000);
            ESP.restart();
        }
    });

    // Reset WiFi and restart in AP mode
    server.on("/reset-wifi", HTTP_GET, []() {
        if (!checkAuth()) return;

        String html = "<!DOCTYPE html><html><head><meta http-equiv='refresh' content='5;url=http://192.168.4.1'></head>";
        html += "<body style='text-align:center;padding:50px;font-family:Arial'>";
        html += "<h1>🔄 Resetting WiFi...</h1>";
        html += "<p>Board will restart in AP mode.</p>";
        html += "<p>Connect to the AP and go to http://192.168.4.1</p>";
        html += "</body></html>";

        server.send(200, "text/html", html);

        delay(2000);

        // Clear WiFi credentials
        preferences.begin("access-ctrl", false);
        preferences.putString("wifiSSID", "");
        preferences.putString("wifiPass", "");
        preferences.putBool("configured", false);
        preferences.putBool("useStaticIP", false);
        preferences.end();

        ESP.restart();
    });

    // Manual unlock
    server.on("/unlock", HTTP_GET, []() {
        if (!checkAuth()) return;
        
        int door = server.arg("door").toInt();
        if (door >= 1 && door <= 2) {
            unlockDoor(door);
        }
        
        server.sendHeader("Location", "/", true);
        server.send(302, "text/plain", "");
    });
    
    // API: Set controller from controller's side
    server.on("/api/set-controller", HTTP_POST, []() {
        DynamicJsonDocument doc(256);
        deserializeJson(doc, server.arg("plain"));
        
        config.controllerIP = doc["controller_ip"].as<String>();
        config.controllerPort = doc["controller_port"] | 8100;
        
        saveConfig();

        server.send(200, "application/json", "{\"success\":true}");

        delay(1000);
        announceToController();
    });

    // API: Update board/door names from controller
    server.on("/api/set-config", HTTP_POST, []() {
        DynamicJsonDocument doc(512);
        deserializeJson(doc, server.arg("plain"));

        bool changed = false;

        if (doc.containsKey("board_name")) {
            String newName = doc["board_name"].as<String>();
            if (newName.length() > 0 && newName != config.boardName) {
                config.boardName = newName;
                changed = true;
                addLiveLog("📝 Board name updated: " + newName);
            }
        }

        if (doc.containsKey("door1_name")) {
            String newName = doc["door1_name"].as<String>();
            if (newName.length() > 0 && newName != doors[0].name) {
                doors[0].name = newName;
                changed = true;
                addLiveLog("📝 Door 1 name updated: " + newName);
            }
        }

        if (doc.containsKey("door2_name")) {
            String newName = doc["door2_name"].as<String>();
            if (newName.length() > 0 && newName != doors[1].name) {
                doors[1].name = newName;
                changed = true;
                addLiveLog("📝 Door 2 name updated: " + newName);
            }
        }

        if (changed) {
            saveConfig();
            server.send(200, "application/json", "{\"success\":true,\"message\":\"Configuration updated\"}");
        } else {
            server.send(200, "application/json", "{\"success\":true,\"message\":\"No changes needed\"}");
        }
    });

    // API: Sync users database and door schedules
    server.on("/api/sync", HTTP_POST, []() {
        String jsonData = server.arg("plain");
        
        addLiveLog("=== SYNC REQUEST RECEIVED ===");
        addLiveLog("Data length: " + String(jsonData.length()) + " bytes");

        // ✅ Parse into a PSRAM-backed document large enough for the full payload.
        // The old 20KB regular-heap document silently failed (NoMemory) once the
        // roster grew past ~20KB, causing boards to keep stale data until reboot.
        BasicJsonDocument<PSRAMAllocator> syncDoc(262144);  // 256KB in PSRAM
        DeserializationError error = deserializeJson(syncDoc, jsonData);

        if (error) {
            addLiveLog("❌ Failed to parse sync JSON: " + String(error.c_str()));
            server.send(500, "application/json", "{\"success\":false,\"message\":\"Parse error\"}");
            return;
        }
        
        if (syncDoc.containsKey("door_schedules")) {
            doorSchedulesDB.clear();
            JsonObject schedules = syncDoc["door_schedules"].as<JsonObject>();
            
            for (JsonPair kv : schedules) {
                doorSchedulesDB[kv.key().c_str()] = kv.value();
            }
            
            addLiveLog("📅 Door schedules loaded");
            for (JsonPair kv : doorSchedulesDB.as<JsonObject>()) {
                String doorNum = kv.key().c_str();
                JsonArray schedulesArray = kv.value();
                addLiveLog("  Door " + doorNum + ": " + String(schedulesArray.size()) + " schedules");
            }
            
            updateDoorModesFromSchedule();
    }

    // ✅ NEW: Handle temp codes
    if (syncDoc.containsKey("temp_codes")) {
            tempCodesDB.clear();
            
            JsonArray codes = syncDoc["temp_codes"].as<JsonArray>();
            JsonArray storedCodes = tempCodesDB.createNestedArray("temp_codes");
            
            for (JsonObject code : codes) {
                JsonObject newCode = storedCodes.createNestedObject();
                newCode["code"] = code["code"];
                newCode["name"] = code["name"];
                newCode["active"] = code["active"] | true;
                newCode["usage_type"] = code["usage_type"];
                newCode["max_uses"] = code["max_uses"] | 1;
                newCode["current_uses"] = code["current_uses"] | 0;
                
                // Copy door access array
                JsonArray doors = newCode.createNestedArray("doors");
                if (code.containsKey("doors")) {
                    for (JsonVariant door : code["doors"].as<JsonArray>()) {
                        doors.add(door.as<int>());
                    }
                }
            }
            
            addLiveLog("🎫 Temp codes loaded: " + String(codes.size()));
            
            // ✅ NEW: Clear per-door usage for codes that were reset on server
            for (JsonObject code : tempCodesDB["temp_codes"].as<JsonArray>()) {
                // If server reset the code (current_uses = 0 and active = true), clear local tracking
                if (code["active"].as<bool>() && code["current_uses"].as<int>() == 0) {
                    clearTempCodeDoorUsage(code["code"].as<String>());
                    addLiveLog("  🔄 Cleared local usage for: " + code["name"].as<String>());
                }
            }
            
            // Debug: print temp codes WITH USAGE COUNTS
            for (JsonObject code : tempCodesDB["temp_codes"].as<JsonArray>()) {
                String doors_str = "";
                for (JsonVariant d : code["doors"].as<JsonArray>()) {
                    doors_str += String(d.as<int>()) + ",";
                }
                addLiveLog("  - " + code["name"].as<String>() + 
                          " (PIN: " + code["code"].as<String>() + 
                          ", Server Uses: " + String(code["current_uses"].as<int>()) + 
                          "/" + String(code["max_uses"].as<int>()) +
                          ", Active: " + String(code["active"].as<bool>()) +
                          ", Doors: " + doors_str + ")");
            }
        }

        // ✅ NEW: Sync door names from controller
if (syncDoc.containsKey("door_names")) {
    JsonObject doorNames = syncDoc["door_names"].as<JsonObject>();
    
    addLiveLog("🚪 Syncing door names from controller...");
    
    if (doorNames.containsKey("1")) {
        String newName = doorNames["1"].as<String>();
        if (newName != doors[0].name) {
            doors[0].name = newName;
            addLiveLog("  Door 1 renamed to: " + newName);
            
            // Save to preferences
            preferences.begin("access-ctrl", false);
            preferences.putString("door1Name", doors[0].name);
            preferences.end();
        }
    }
    
    if (doorNames.containsKey("2")) {
        String newName = doorNames["2"].as<String>();
        if (newName != doors[1].name) {
            doors[1].name = newName;
            addLiveLog("  Door 2 renamed to: " + newName);
            
            // Save to preferences
            preferences.begin("access-ctrl", false);
            preferences.putString("door2Name", doors[1].name);
            preferences.end();
        }
    }
}

// ✅ Load unlock durations from sync
if (syncDoc.containsKey("unlock_durations")) {
    JsonObject durations = syncDoc["unlock_durations"];

    if (durations.containsKey("door1")) {
        doors[0].unlockDuration = durations["door1"].as<int>();
        addLiveLog("⏱️ Door 1 unlock: " + String(doors[0].unlockDuration) + "ms");
    }

    if (durations.containsKey("door2")) {
        doors[1].unlockDuration = durations["door2"].as<int>();
        addLiveLog("⏱️ Door 2 unlock: " + String(doors[1].unlockDuration) + "ms");
    }

    // Save updated durations to flash
    saveConfig();
}

// ✅ FIXED: Only trigger relays when emergency mode CHANGES (not on every sync)

// Sync emergency mode (using only config.emergencyMode string)
if (syncDoc.containsKey("emergency_mode")) {
    const char* mode = syncDoc["emergency_mode"];
    String newMode = (mode == nullptr || strlen(mode) == 0) ? "" : String(mode);

    addLiveLog("📥 Emergency mode from server: '" + newMode + "' (current: '" + config.emergencyMode + "')");

    // Only take action if mode CHANGED
    if (newMode != config.emergencyMode) {
        addLiveLog("⚡ Emergency mode CHANGED - applying...");

        if (newMode == "") {
            // Reset to normal
            config.emergencyMode = "";
            addLiveLog("✅✅✅ Emergency mode RESET - Normal operation ✅✅✅");

            // Release all doors if they were locked by emergency
            for (int i = 0; i < 2; i++) {
                // Only reset if no per-door override
                if (doors[i].emergencyOverride == "") {
                    digitalWrite(doors[i].relayPin, LOW);
                    doors[i].isUnlocked = false;
                    doors[i].scheduledUnlock = false;
                }
            }

            // Re-apply schedules
            updateDoorModesFromSchedule();
        }
        else if (newMode == "lock") {
            // Emergency lockdown
            config.emergencyMode = "lock";
            addLiveLog("🚨🚨🚨 EMERGENCY LOCKDOWN ACTIVATED 🚨🚨🚨");

            // Lock all doors immediately
            for (int i = 0; i < 2; i++) {
                digitalWrite(doors[i].relayPin, LOW);
                doors[i].isUnlocked = false;
                doors[i].scheduledUnlock = false;
            }

            beepPattern(3, 200, 100);  // 3 beeps - lockdown
        }
        else if (newMode == "unlock") {
            // Emergency evacuation
            config.emergencyMode = "unlock";
            addLiveLog("🚨🚨🚨 EMERGENCY EVACUATION MODE ACTIVATED 🚨🚨🚨");

            // Unlock all doors immediately
            for (int i = 0; i < 2; i++) {
                digitalWrite(doors[i].relayPin, HIGH);
                doors[i].isUnlocked = true;
                doors[i].unlockUntil = 0xFFFFFFFF;  // Stay unlocked
                doors[i].scheduledUnlock = false;
            }

            beepPattern(5, 100, 100);  // 5 fast beeps - evacuation
        }
    } else {
        addLiveLog("ℹ️ Emergency mode unchanged - no action needed");
    }
}

// ✅ FIXED: Door overrides - only trigger when override CHANGES
if (syncDoc.containsKey("door_overrides")) {
    JsonArray overrides = syncDoc["door_overrides"];

    for (JsonObject override : overrides) {
        int doorNum = override["door_number"];
        const char* overrideMode = override["mode"];

        if (doorNum >= 1 && doorNum <= 2) {
            int idx = doorNum - 1;
            String newOverride = (overrideMode == nullptr || strlen(overrideMode) == 0) ? "" : String(overrideMode);

            addLiveLog("📥 Door " + String(doorNum) + " override from server: '" + newOverride + "' (current: '" + doors[idx].emergencyOverride + "')");

            // Only take action if override CHANGED
            if (newOverride != doors[idx].emergencyOverride) {
                addLiveLog("⚡ Door " + String(doorNum) + " override CHANGED - applying...");

                if (newOverride == "") {
                    doors[idx].emergencyOverride = "";
                    addLiveLog("✅ " + doors[idx].name + " override reset");
                    // Re-apply schedule for this door
                    String scheduleMode = checkDoorScheduleMode(doorNum);
                    if (scheduleMode == "unlock") {
                        digitalWrite(doors[idx].relayPin, HIGH);
                        doors[idx].isUnlocked = true;
                        doors[idx].scheduledUnlock = true;
                    } else {
                        digitalWrite(doors[idx].relayPin, LOW);
                        doors[idx].isUnlocked = false;
                        doors[idx].scheduledUnlock = false;
                    }
                }
                else if (newOverride == "lock") {
                    doors[idx].emergencyOverride = "lock";
                    digitalWrite(doors[idx].relayPin, LOW);
                    doors[idx].isUnlocked = false;
                    addLiveLog("🔒 " + doors[idx].name + " OVERRIDE LOCKED");
                }
                else if (newOverride == "unlock") {
                    doors[idx].emergencyOverride = "unlock";
                    digitalWrite(doors[idx].relayPin, HIGH);
                    doors[idx].isUnlocked = true;
                    doors[idx].unlockUntil = 0xFFFFFFFF;
                    addLiveLog("🔓 " + doors[idx].name + " OVERRIDE UNLOCKED");
                }
            } else {
                addLiveLog("ℹ️ Door " + String(doorNum) + " override unchanged - no action needed");
            }
        }
    }
}
        
// ✅ NEW: Handle user schedules
if (syncDoc.containsKey("user_schedules")) {
    userSchedulesDB.clear();
    
    JsonObject schedules = syncDoc["user_schedules"].as<JsonObject>();
    
    for (JsonPair userSchedule : schedules) {
        String userId = userSchedule.key().c_str();
        JsonArray scheduleArray = userSchedule.value().as<JsonArray>();
        
        JsonArray storedSchedules = userSchedulesDB.createNestedArray(userId);
        
        for (JsonObject sched : scheduleArray) {
            JsonObject newSched = storedSchedules.createNestedObject();
            newSched["day"] = sched["day"];
            newSched["start"] = sched["start"].as<String>();
            newSched["end"] = sched["end"].as<String>();
        }
    }
    
    addLiveLog("📅 User schedules loaded: " + String(userSchedulesDB.size()) + " users");
}

        if (saveUsersDB(jsonData)) {
            addLiveLog("✅ Users database synced");
            
            if (usersDB.containsKey("users")) {
                addLiveLog("📝 " + String(usersDB["users"].size()) + " users loaded");
            }
            
            server.send(200, "application/json", "{\"success\":true}");
        } else {
            addLiveLog("❌ Failed to save users database");
            server.send(500, "application/json", "{\"success\":false,\"message\":\"Failed to save\"}");
        }
    });


        
    
    // Emergency API endpoints
    server.on("/api/emergency-lock", HTTP_POST, []() {
        addLiveLog("🚨 EMERGENCY LOCK ACTIVATED");
        
        config.emergencyMode = "lock";
        config.emergencyAutoResetAt = 0;
        
        digitalWrite(doors[0].relayPin, LOW);
        digitalWrite(doors[1].relayPin, LOW);
        doors[0].isUnlocked = false;
        doors[1].isUnlocked = false;
        doors[0].scheduledUnlock = false;
        doors[1].scheduledUnlock = false;
        
        beepEmergency();
        
        server.send(200, "application/json", "{\"success\":true}");
    });
    
    server.on("/api/emergency-unlock", HTTP_POST, []() {
        DynamicJsonDocument doc(256);
        deserializeJson(doc, server.arg("plain"));
        
        int duration = doc["duration"] | 1800;
        
        addLiveLog("🚨 EMERGENCY UNLOCK ACTIVATED (duration: " + String(duration) + "s)");
        
        config.emergencyMode = "unlock";
        config.emergencyAutoResetAt = millis() + (duration * 1000);
        
        digitalWrite(doors[0].relayPin, HIGH);
        digitalWrite(doors[1].relayPin, HIGH);
        doors[0].isUnlocked = true;
        doors[1].isUnlocked = true;
        
        beepEmergency();
        
        server.send(200, "application/json", "{\"success\":true}");
    });
    
    server.on("/api/emergency-reset", HTTP_POST, []() {
        addLiveLog("✅ EMERGENCY MODE RESET");
        
        config.emergencyMode = "";
        config.emergencyAutoResetAt = 0;
        
        updateDoorModesFromSchedule();
        
        beep(200);
        
        server.send(200, "application/json", "{\"success\":true}");
    });
    
    server.on("/api/door-override", HTTP_POST, []() {
        DynamicJsonDocument doc(256);
        deserializeJson(doc, server.arg("plain"));
        
        int doorNumber = doc["door_number"];
        String override = doc["override"].as<String>();
        
        if (doorNumber < 1 || doorNumber > 2) {
            server.send(400, "application/json", "{\"success\":false,\"message\":\"Invalid door number\"}");
            return;
        }
        
        doors[doorNumber - 1].emergencyOverride = override;
        
        if (override == "lock") {
            addLiveLog("🚨 Door " + String(doorNumber) + " EMERGENCY LOCKED");
            digitalWrite(doors[doorNumber - 1].relayPin, LOW);
            doors[doorNumber - 1].isUnlocked = false;
            doors[doorNumber - 1].scheduledUnlock = false;
            beepEmergency();
        } else if (override == "unlock") {
            addLiveLog("🚨 Door " + String(doorNumber) + " EMERGENCY UNLOCKED");
            digitalWrite(doors[doorNumber - 1].relayPin, HIGH);
            doors[doorNumber - 1].isUnlocked = true;
            beepEmergency();
        } else {
            addLiveLog("✅ Door " + String(doorNumber) + " override reset");
            
            String scheduleMode = checkDoorScheduleMode(doorNumber);
            if (scheduleMode == "unlock") {
                digitalWrite(doors[doorNumber - 1].relayPin, HIGH);
                doors[doorNumber - 1].isUnlocked = true;
                doors[doorNumber - 1].scheduledUnlock = true;
            } else {
                digitalWrite(doors[doorNumber - 1].relayPin, LOW);
                doors[doorNumber - 1].isUnlocked = false;
                doors[doorNumber - 1].scheduledUnlock = false;
            }
            
            beep(200);
        }
        
        server.send(200, "application/json", "{\"success\":true}");
    });

    // ===== OTA UPDATE PAGE =====
    server.on("/update", HTTP_GET, []() {
        if (!checkAuth()) return;
        
        String html = "<!DOCTYPE html><html><head>";
        html += "<meta name='viewport' content='width=device-width, initial-scale=1'>";
        html += "<title>Firmware Update - " + config.boardName + "</title>";
        html += "<style>";
        html += "body{font-family:Arial;margin:0;padding:20px;background:#1a1a2e;color:#fff;min-height:100vh}";
        html += ".container{max-width:500px;margin:0 auto;background:#16213e;padding:30px;border-radius:15px;box-shadow:0 10px 30px rgba(0,0,0,0.3)}";
        html += "h1{color:#4ade80;margin-bottom:10px;font-size:28px}";
        html += ".subtitle{color:#94a3b8;margin-bottom:30px}";
        html += ".upload-area{border:3px dashed #4ade80;border-radius:12px;padding:40px;text-align:center;margin:20px 0;transition:all 0.3s}";
        html += ".upload-area:hover{background:rgba(74,222,128,0.1)}";
        html += ".upload-area.dragover{background:rgba(74,222,128,0.2);border-color:#22c55e}";
        html += "input[type=file]{display:none}";
        html += ".file-label{display:inline-block;background:#4ade80;color:#1a1a2e;padding:12px 30px;border-radius:8px;cursor:pointer;font-weight:bold;transition:all 0.3s}";
        html += ".file-label:hover{background:#22c55e;transform:translateY(-2px)}";
        html += ".file-name{margin-top:15px;color:#94a3b8;font-size:14px}";
        html += "button{background:linear-gradient(135deg,#4ade80,#22c55e);color:#1a1a2e;border:none;padding:15px 40px;font-size:18px;font-weight:bold;border-radius:10px;cursor:pointer;width:100%;margin-top:20px;transition:all 0.3s}";
        html += "button:hover:not(:disabled){transform:translateY(-2px);box-shadow:0 5px 20px rgba(74,222,128,0.4)}";
        html += "button:disabled{background:#4b5563;cursor:not-allowed;transform:none;box-shadow:none}";
        html += ".progress{display:none;margin-top:20px}";
        html += ".progress-bar{height:20px;background:#374151;border-radius:10px;overflow:hidden}";
        html += ".progress-fill{height:100%;background:linear-gradient(90deg,#4ade80,#22c55e);width:0%;transition:width 0.3s;border-radius:10px}";
        html += ".progress-text{text-align:center;margin-top:10px;color:#4ade80;font-weight:bold}";
        html += ".warning{background:rgba(251,191,36,0.2);border-left:4px solid #fbbf24;padding:15px;border-radius:0 8px 8px 0;margin:20px 0}";
        html += ".warning h4{color:#fbbf24;margin-bottom:5px}";
        html += ".warning p{color:#fef3c7;font-size:14px;margin:0}";
        html += ".info{background:rgba(59,130,246,0.2);border-left:4px solid #3b82f6;padding:15px;border-radius:0 8px 8px 0;margin:20px 0}";
        html += ".info p{color:#bfdbfe;font-size:14px;margin:0}";
        html += ".back-btn{display:inline-block;color:#94a3b8;text-decoration:none;margin-bottom:20px;font-size:14px}";
        html += ".back-btn:hover{color:#fff}";
        html += ".version{background:#374151;padding:10px 15px;border-radius:8px;margin-bottom:20px;font-size:14px}";
        html += ".version span{color:#4ade80;font-weight:bold}";
        html += "</style></head><body>";
        html += "<div class='container'>";
        html += "<a href='/' class='back-btn'>← Back to Dashboard</a>";
        html += "<h1>🔄 Firmware Update</h1>";
        html += "<p class='subtitle'>Update your board over WiFi (OTA)</p>";
        
        html += "<div class='version'>Current: <span>v" + String(FIRMWARE_VERSION) + "</span> | Board: <span>" + config.boardName + "</span> | IP: <span>" + WiFi.localIP().toString() + "</span></div>";
        
        html += "<div class='warning'>";
        html += "<h4>⚠️ Warning</h4>";
        html += "<p>Do not disconnect power during update. Board will restart automatically when complete.</p>";
        html += "</div>";
        
        html += "<form method='POST' action='/update' enctype='multipart/form-data' id='uploadForm'>";
        html += "<div class='upload-area' id='dropZone'>";
        html += "<label class='file-label' for='firmware'>📁 Choose .bin File</label>";
        html += "<input type='file' id='firmware' name='firmware' accept='.bin' onchange='fileSelected(this)'>";
        html += "<div class='file-name' id='fileName'>No file selected</div>";
        html += "</div>";
        html += "<button type='submit' id='uploadBtn' disabled>⬆️ Upload & Install</button>";
        html += "</form>";
        
        html += "<div class='progress' id='progressArea'>";
        html += "<div class='progress-bar'><div class='progress-fill' id='progressFill'></div></div>";
        html += "<div class='progress-text' id='progressText'>Uploading... 0%</div>";
        html += "</div>";
        
        html += "<div class='info'>";
        html += "<p>💡 <b>How to get .bin file:</b> Arduino IDE → Sketch → Export Compiled Binary</p>";
        html += "</div>";
        
        html += "</div>";
        
        // JavaScript
        html += "<script>";
        html += "function fileSelected(input){";
        html += "  var name=input.files[0]?input.files[0].name:'No file selected';";
        html += "  var size=input.files[0]?(input.files[0].size/1024).toFixed(1)+' KB':'';";
        html += "  document.getElementById('fileName').textContent='📄 '+name+(size?' ('+size+')':'');";
        html += "  document.getElementById('uploadBtn').disabled=!input.files[0];";
        html += "}";
        
        html += "var dropZone=document.getElementById('dropZone');";
        html += "['dragenter','dragover','dragleave','drop'].forEach(e=>{";
        html += "  dropZone.addEventListener(e,function(ev){ev.preventDefault();ev.stopPropagation();});";
        html += "});";
        html += "dropZone.addEventListener('dragover',function(){this.classList.add('dragover');});";
        html += "dropZone.addEventListener('dragleave',function(){this.classList.remove('dragover');});";
        html += "dropZone.addEventListener('drop',function(e){";
        html += "  this.classList.remove('dragover');";
        html += "  document.getElementById('firmware').files=e.dataTransfer.files;";
        html += "  fileSelected(document.getElementById('firmware'));";
        html += "});";
        
        html += "document.getElementById('uploadForm').onsubmit=function(e){";
        html += "  e.preventDefault();";
        html += "  var formData=new FormData(this);";
        html += "  var xhr=new XMLHttpRequest();";
        html += "  document.getElementById('uploadBtn').disabled=true;";
        html += "  document.getElementById('uploadBtn').textContent='⏳ Uploading...';";
        html += "  document.getElementById('progressArea').style.display='block';";
        html += "  xhr.upload.onprogress=function(e){";
        html += "    if(e.lengthComputable){";
        html += "      var pct=Math.round((e.loaded/e.total)*100);";
        html += "      document.getElementById('progressFill').style.width=pct+'%';";
        html += "      document.getElementById('progressText').textContent='Uploading... '+pct+'%';";
        html += "    }";
        html += "  };";
        html += "  xhr.onload=function(){";
        html += "    if(xhr.status==200){";
        html += "      document.getElementById('progressText').textContent='✅ Success! Rebooting in 5 seconds...';";
        html += "      document.getElementById('progressFill').style.width='100%';";
        html += "      setTimeout(function(){location.href='/';},8000);";
        html += "    }else{";
        html += "      document.getElementById('progressText').textContent='❌ Failed: '+xhr.responseText;";
        html += "      document.getElementById('uploadBtn').disabled=false;";
        html += "      document.getElementById('uploadBtn').textContent='⬆️ Upload & Install';";
        html += "    }";
        html += "  };";
        html += "  xhr.onerror=function(){";
        html += "    document.getElementById('progressText').textContent='❌ Connection error';";
        html += "    document.getElementById('uploadBtn').disabled=false;";
        html += "    document.getElementById('uploadBtn').textContent='⬆️ Upload & Install';";
        html += "  };";
        html += "  xhr.open('POST','/update',true);";
        html += "  xhr.send(formData);";
        html += "};";
        html += "</script>";
        
        html += "</body></html>";
        
        server.send(200, "text/html", html);
    });
    
    // ===== OTA UPDATE HANDLER (receives the firmware) =====
    server.on("/update", HTTP_POST, []() {
        // This runs AFTER upload completes
        bool hasError = Update.hasError();
        
        server.sendHeader("Connection", "close");
        if (hasError) {
            server.send(500, "text/plain", "Update FAILED: " + String(Update.errorString()));
            addLiveLog("❌ OTA Update FAILED: " + String(Update.errorString()));
        } else {
            server.send(200, "text/plain", "Update successful! Rebooting...");
            addLiveLog("✅ OTA Update SUCCESSFUL! Rebooting...");
            delay(1000);
            ESP.restart();
        }
    }, []() {
        // This runs DURING upload (called multiple times)
        HTTPUpload& upload = server.upload();
        
        if (upload.status == UPLOAD_FILE_START) {
            addLiveLog("📥 OTA Update starting: " + upload.filename);
            
            // Stop other tasks during update
            uint32_t maxSketchSpace = (ESP.getFreeSketchSpace() - 0x1000) & 0xFFFFF000;
            addLiveLog("📊 Free space: " + String(maxSketchSpace) + " bytes");
            
            if (!Update.begin(maxSketchSpace)) {
                addLiveLog("❌ Not enough space: " + String(Update.errorString()));
            }
        } 
        else if (upload.status == UPLOAD_FILE_WRITE) {
            // Write firmware chunk
            esp_task_wdt_reset();  // OTA transfer can exceed the WDT timeout in one call
            if (Update.write(upload.buf, upload.currentSize) != upload.currentSize) {
                addLiveLog("❌ Write error: " + String(Update.errorString()));
            }
        }
        else if (upload.status == UPLOAD_FILE_END) {
            if (Update.end(true)) {
                addLiveLog("✅ Upload complete: " + String(upload.totalSize) + " bytes");
            } else {
                addLiveLog("❌ Upload failed: " + String(Update.errorString()));
            }
        }
    });
    
    // Restart
    server.on("/restart", HTTP_GET, []() {
        if (!checkAuth()) return;
        
        server.send(200, "text/html", "<html><body><h1>Restarting...</h1></body></html>");
        delay(1000);
        ESP.restart();
    });
    
    server.begin();
    addLiveLog("🌐 Web interface started at http://" + WiFi.localIP().toString());
}

// ===============================================================
// WATCHDOG + RESET DIAGNOSTICS
// ===============================================================

String resetReasonString() {
    switch (esp_reset_reason()) {
        case ESP_RST_POWERON:  return "Power-on";
        case ESP_RST_EXT:      return "External reset";
        case ESP_RST_SW:       return "Software reset (ESP.restart)";
        case ESP_RST_PANIC:    return "PANIC / exception";
        case ESP_RST_INT_WDT:  return "Interrupt watchdog";
        case ESP_RST_TASK_WDT: return "Task watchdog (loop hang)";
        case ESP_RST_WDT:      return "Other watchdog";
        case ESP_RST_BROWNOUT: return "BROWNOUT (power dip)";
        case ESP_RST_SDIO:     return "SDIO reset";
        default:               return "Unknown";
    }
}

void initWatchdog() {
    addLiveLog("🐕 Initializing watchdog (" + String(WDT_TIMEOUT_SECONDS) + "s)...");
#if ESP_IDF_VERSION_MAJOR >= 5
    // Arduino core 3.x already inits the Task WDT; just adjust the timeout.
    esp_task_wdt_config_t twdt_config = {
        .timeout_ms = WDT_TIMEOUT_SECONDS * 1000,
        .idle_core_mask = 0,
        .trigger_panic = true,
    };
    esp_task_wdt_reconfigure(&twdt_config);
#else
    esp_task_wdt_init(WDT_TIMEOUT_SECONDS, true);  // panic=true -> chip reset on trip
#endif
    esp_task_wdt_add(NULL);  // subscribe the task that runs loop()
    esp_task_wdt_reset();
}

// ===============================================================
// SETUP
// ===============================================================

void setup() {
    Serial.begin(115200);
    delay(1000);

    // Create the live-log mutex before anything logs (networkTask, which shares
    // the buffer, is not started until the very end of setup()).
    liveLogMutex = xSemaphoreCreateMutex();

    Serial.println("\n\n=======================================================");
    Serial.println("🔐 ACCESS CONTROL SYSTEM - ESP32 FIRMWARE v3.2");
    Serial.println("   With Live Logs & Raw Wiegand Data Viewer");
    Serial.println("=======================================================");

    addLiveLog("=== SYSTEM BOOT ===");
    addLiveLog("🔁 Last reset reason: " + resetReasonString());
    initWatchdog();
    
    if (!SPIFFS.begin(true)) {
    addLiveLog("❌ SPIFFS initialization failed");
} else {
    addLiveLog("✅ SPIFFS initialized");
}

// Check PSRAM
if (psramFound()) {
    addLiveLog("✅ PSRAM found: " + String(ESP.getPsramSize() / 1024) + " KB");
    addLiveLog("  Free PSRAM: " + String(ESP.getFreePsram() / 1024) + " KB");
} else {
    addLiveLog("⚠️ PSRAM not found - using standard RAM");
}

// Validate pins for N16R8
validatePins();

loadConfig();

// ✅ Get MAC address from eFuse (always available, doesn't depend on WiFi)
uint8_t mac[6];
esp_read_mac(mac, ESP_MAC_WIFI_STA);
char macStr[18];
sprintf(macStr, "%02X:%02X:%02X:%02X:%02X:%02X", mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
config.macAddress = String(macStr);
addLiveLog("🔖 MAC Address: " + config.macAddress);

// Build the AP-fallback SSID once here (single-threaded at boot) so it is
// immutable by the time networkTask (Core 0) or the web handler (Core 1) touch it.
apFallbackSSID = "AccessControl-" + String((uint32_t)ESP.getEfuseMac(), HEX);

// Initialize WiFi mode
WiFi.mode(WIFI_STA);

    pinMode(LED_STATUS, OUTPUT);
    pinMode(BEEPER, OUTPUT);
    
    doors[0].relayPin = RELAY_DOOR1;
    doors[0].rexPin = REX_BUTTON_DOOR1;
    doors[0].readerLedPin = READER1_LED;      // ✅ NEW
    doors[0].readerBeepPin = READER1_BEEP;    // ✅ NEW
    doors[0].wiegand.d0Pin = WIEGAND_D0_DOOR1;
    doors[0].wiegand.d1Pin = WIEGAND_D1_DOOR1;
    doors[0].isUnlocked = false;
    pinMode(doors[0].relayPin, OUTPUT);
    pinMode(doors[0].rexPin, INPUT_PULLUP);
    pinMode(doors[0].readerLedPin, OUTPUT);   // ✅ NEW
    pinMode(doors[0].readerBeepPin, OUTPUT);  // ✅ NEW
    pinMode(doors[0].wiegand.d0Pin, INPUT_PULLUP);
    pinMode(doors[0].wiegand.d1Pin, INPUT_PULLUP);
    digitalWrite(doors[0].relayPin, LOW);
    digitalWrite(doors[0].readerLedPin, LOW); // ✅ NEW
    digitalWrite(doors[0].readerBeepPin, LOW);// ✅ NEW


    doors[1].relayPin = RELAY_DOOR2;
    doors[1].rexPin = REX_BUTTON_DOOR2;
    doors[1].readerLedPin = READER2_LED;      // ✅ NEW
    doors[1].readerBeepPin = READER2_BEEP;    // ✅ NEW
    doors[1].wiegand.d0Pin = WIEGAND_D0_DOOR2;
    doors[1].wiegand.d1Pin = WIEGAND_D1_DOOR2;
    doors[1].isUnlocked = false;
    pinMode(doors[1].relayPin, OUTPUT);
    pinMode(doors[1].rexPin, INPUT_PULLUP);
    pinMode(doors[1].readerLedPin, OUTPUT);   // ✅ NEW
    pinMode(doors[1].readerBeepPin, OUTPUT);  // ✅ NEW
    pinMode(doors[1].wiegand.d0Pin, INPUT_PULLUP);
    pinMode(doors[1].wiegand.d1Pin, INPUT_PULLUP);
    digitalWrite(doors[1].relayPin, LOW);
    digitalWrite(doors[1].readerLedPin, LOW); // ✅ NEW
    digitalWrite(doors[1].readerBeepPin, LOW);// ✅ NEW
    
    door1Wiegand = &doors[0].wiegand;
    door2Wiegand = &doors[1].wiegand;

    addLiveLog("✅ GPIO initialized");

    // Load user database FIRST - so we can work offline
    loadUsersDB();

    // Attach Wiegand interrupts - needed for offline operation
    attachInterrupt(digitalPinToInterrupt(WIEGAND_D0_DOOR1), door1_D0_ISR, FALLING);
    attachInterrupt(digitalPinToInterrupt(WIEGAND_D1_DOOR1), door1_D1_ISR, FALLING);
    attachInterrupt(digitalPinToInterrupt(WIEGAND_D0_DOOR2), door2_D0_ISR, FALLING);
    attachInterrupt(digitalPinToInterrupt(WIEGAND_D1_DOOR2), door2_D1_ISR, FALLING);
    addLiveLog("✅ Wiegand interrupts attached");

    // Check if board needs initial configuration
    if (!config.configured || config.wifiSSID.length() == 0) {
        addLiveLog("⚠️  No WiFi configuration - starting setup portal");
        startWiFiManager();
    }

    // Try to connect to WiFi
    if (connectWiFi()) {
        setupWebInterface();

        if (config.controllerIP.length() > 0) {
            delay(2000);
            announceToController();
        }

        sendHeartbeat();

        addLiveLog("🔄 Performing initial schedule check...");
        delay(3000);
        updateDoorModesFromSchedule();

    } else {
        // WiFi failed but board is configured - work in OFFLINE MODE
        addLiveLog("⚠️  WiFi unavailable - running in OFFLINE MODE");
        addLiveLog("📋 Using cached user database (" + String(usersDB["users"].size()) + " users)");
        addLiveLog("🔄 Will retry WiFi connection in background");

        // Still set up web interface - needed for AP fallback mode
        setupWebInterface();
    }
    
    // ✅ Start the Core 0 network task (outbound HTTP: heartbeat, log sending,
    // WiFi reconnect, NTP). Door/relay control stays on Core 1 (this loop task).
    logQueueMutex = xSemaphoreCreateMutex();
    xTaskCreatePinnedToCore(
        networkTask,          // task function
        "networkTask",        // name
        12288,                // stack (bytes) - HTTPClient + JSON + String headroom
        NULL,                 // param
        1,                    // priority (same as loopTask)
        &networkTaskHandle,   // handle
        0                     // pin to Core 0 (loop() runs on Core 1)
    );
    addLiveLog("🌐 Network task started on Core 0");

    addLiveLog("=======================================================");
    addLiveLog("✅ System ready!");
    addLiveLog("=======================================================");

    beepSuccess();
}

// ===============================================================
// CORE 0 NETWORK TASK
// All OUTBOUND network I/O lives here so the Core 1 access path is never
// blocked by a heartbeat / log send / reconnect. This task never touches
// relays or door state.
// ===============================================================
void networkTask(void* param) {
    // Subscribe this task to the watchdog too (it does blocking HTTP with 2s
    // timeouts, well under WDT_TIMEOUT_SECONDS).
    esp_task_wdt_add(NULL);

    unsigned long lastWiFiCheckN = 0;
    unsigned long lastHeartbeatN = 0;
    unsigned long lastLogRetryN = 0;

    for (;;) {
        esp_task_wdt_reset();
        unsigned long now = millis();

        // --- WiFi watchdog / non-blocking auto-reconnect (every 10s) ---
        if (now - lastWiFiCheckN >= 10000) {
            lastWiFiCheckN = now;

            if (WiFi.status() != WL_CONNECTED) {
                wifiReconnectAttempts++;

                if (wifiReconnectAttempts <= 3) {
                    addLiveLog("🔄 WiFi reconnecting... (attempt " + String(wifiReconnectAttempts) + ")");
                } else if (!apFallbackMode) {
                    addLiveLog("⚠️ WiFi DOWN (attempt " + String(wifiReconnectAttempts) + "/10)");
                }

                if (!apFallbackMode) {
                    WiFi.disconnect();
                }
                WiFi.begin(config.wifiSSID.c_str(), config.wifiPassword.c_str());

                if (wifiReconnectAttempts >= 10 && !apFallbackMode) {
                    addLiveLog("⚠️ Starting AP fallback mode");
                    startAPFallbackMode();
                }
            } else {
                if (wifiReconnectAttempts > 0) {
                    addLiveLog("✅ WiFi reconnected! IP: " + WiFi.localIP().toString());
                    wifiReconnectAttempts = 0;

                    if (apFallbackMode) {
                        stopAPFallbackMode();
                    }

                    configTime(-5 * 3600, 3600, "pool.ntp.org", "time.nist.gov");
                    addLiveLog("🕐 NTP time sync initiated");

                    if (config.controllerIP.length() > 0) {
                        announceToController();
                    }
                }

                static unsigned long lastNtpCheck = 0;
                static bool ntpSynced = false;
                if (now - lastNtpCheck >= 300000) {  // 5 minutes
                    lastNtpCheck = now;
                    struct tm timeinfo;
                    if (getLocalTime(&timeinfo, 100)) {
                        if (!ntpSynced) {
                            addLiveLog("🕐 NTP synced: " + String(timeinfo.tm_hour) + ":" +
                                       String(timeinfo.tm_min < 10 ? "0" : "") + String(timeinfo.tm_min));
                            ntpSynced = true;
                        }
                    } else {
                        addLiveLog("⚠️ NTP not synced - retrying...");
                        configTime(-5 * 3600, 3600, "pool.ntp.org", "time.nist.gov");
                        ntpSynced = false;
                    }
                }
            }
        }

        // --- Heartbeat (every HEARTBEAT_INTERVAL) ---
        if (now - lastHeartbeatN >= HEARTBEAT_INTERVAL) {
            lastHeartbeatN = now;
            if (WiFi.status() == WL_CONNECTED) {
                if (sendHeartbeat()) {
                    sendQueuedLogs();  // controller online - flush any queued logs
                }
            }
        }

        // --- Retry queued logs (every 5s) ---
        if (now - lastLogRetryN >= 5000) {
            lastLogRetryN = now;
            if (WiFi.status() == WL_CONNECTED) {
                sendQueuedLogs();  // safe/no-op when the queue is empty
            }
        }

        vTaskDelay(pdMS_TO_TICKS(20));  // yield to Core 0 idle / other tasks
    }
}

// ===============================================================
// MAIN LOOP (Core 1) - time-critical access path + web + door control.
// No outbound network I/O here (that's networkTask on Core 0).
// ===============================================================
void loop() {
    unsigned long now = millis();
    unsigned long loopStart = now;

    // Feed the watchdog once per iteration. If the access path ever wedges,
    // this stops getting fed and the chip auto-resets after WDT_TIMEOUT_SECONDS.
    esp_task_wdt_reset();

    // ----- Loop timing diagnostics -----
    static unsigned long lastLoopHealthCheck = 0;
    static unsigned long loopCount = 0;
    static unsigned long slowLoopCount = 0;

    loopCount++;
    if (now - lastLoopHealthCheck >= 30000) {
        float avgLoopTime = 30000.0 / loopCount;
        addLiveLog("📊 Loop health: " + String(loopCount) + " iterations in 30s (avg " +
                   String(avgLoopTime, 1) + "ms, " + String(slowLoopCount) + " slow)");
        loopCount = 0;
        slowLoopCount = 0;
        lastLoopHealthCheck = now;
    }

    // ----- Time-critical + web + door control -----
    server.handleClient();
    checkWiegandData();
    checkDoorLocks();
    checkReaderFeedback();
    checkOnboardFeedback();

    if (now - lastEmergencyCheck >= 1000) {
        lastEmergencyCheck = now;
        checkEmergencyAutoReset();
    }

    if (now - lastScheduleCheck >= SCHEDULE_CHECK_INTERVAL) {
        lastScheduleCheck = now;
        if (config.emergencyMode == "") {
            updateDoorModesFromSchedule();
        }
    }

    // REX buttons - non-blocking debounce
    static unsigned long lastRexPress[2] = {0, 0};
    for (int r = 0; r < 2; r++) {
        if (digitalRead(doors[r].rexPin) == LOW && (now - lastRexPress[r] > 1000)) {
            lastRexPress[r] = now;
            addLiveLog("🚪 REX button pressed - Door " + String(r + 1));
            unlockDoor(r + 1);
        }
    }

    // ----- Slow loop detection -----
    unsigned long loopDuration = millis() - loopStart;
    if (loopDuration > 100) {
        slowLoopCount++;
        if (loopDuration > 500) {
            addLiveLog("⚠️ SLOW LOOP: " + String(loopDuration) + "ms - card reads may be delayed!");
        }
    }

    delay(2);  // small yield; network I/O now runs on Core 0
}
