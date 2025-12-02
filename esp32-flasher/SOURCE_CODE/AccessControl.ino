/*
 * ===============================================================
 *  PROFESSIONAL ACCESS CONTROL SYSTEM - ESP32 FIRMWARE
 *  With Emergency Override, Real-Time Schedule & LIVE LOGS
 * ===============================================================
 *  NEW: Real-time log viewer in web dashboard showing raw Wiegand data
 * ===============================================================
 */

#include <WiFi.h>
#include <WebServer.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <SPIFFS.h>
#include <Preferences.h>
#include <ESPmDNS.h>

// ===============================================================
// CONFIGURATION
// ===============================================================

// GPIO Pin Definitions
#define WIEGAND_D0_DOOR1    21
#define WIEGAND_D1_DOOR1    22
#define WIEGAND_D0_DOOR2    14
#define WIEGAND_D1_DOOR2    27
#define RELAY_DOOR1         26
#define RELAY_DOOR2         13
#define REX_BUTTON_DOOR1    25
#define REX_BUTTON_DOOR2    33
#define LED_STATUS          2   // Built-in LED
#define BEEPER              32  // ESP32 onboard beeper

// ✅ NEW: Reader LED and Beep Control
#define READER1_LED         23  // Door 1 reader LED control
#define READER1_BEEP        19  // Door 1 reader beep control
#define READER2_LED         18  // Door 2 reader LED control
#define READER2_BEEP        5   // Door 2 reader beep control

// Default Settings
#define DEFAULT_UNLOCK_DURATION   3000  // 3 seconds in milliseconds
#define HEARTBEAT_INTERVAL        60000 // 60 seconds
#define LOG_QUEUE_MAX             500
#define WIEGAND_TIMEOUT           100    // milliseconds
#define SCHEDULE_CHECK_INTERVAL   60000 // Check schedules every 60 seconds
#define READER_BEEP_SUCCESS_MS    100
#define READER_BEEP_ERROR_MS      500
#define READER_LED_SUCCESS_MS     2000
#define READER_LED_ERROR_MS       1000

// NEW: Live log buffer
#define LIVE_LOG_BUFFER_SIZE 200
String liveLogBuffer[LIVE_LOG_BUFFER_SIZE];
int liveLogIndex = 0;
unsigned long liveLogCounter = 0;

// WiFi Manager Settings
#define WIFI_PORTAL_TIMEOUT       300000 // 5 minutes

// Web Interface Credentials
#define WEB_USERNAME "admin"
#define WEB_PASSWORD "admin"

// ===============================================================
// GLOBAL OBJECTS
// ===============================================================

WebServer server(80);
Preferences preferences;
HTTPClient http;

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
    bool isTempCode;  // ✅ NEW: Track if this was a temp code
};

// ✅ AccessLog struct (should already exist - if not, add it)
struct AccessLog {
    String timestamp;
    int doorNumber;
    String userName;
    String credential;
    String credentialType;
    bool granted;
    String reason;
};

int door1UnlockDuration = 3000;  // Default 3 seconds
int door2UnlockDuration = 3000;  // Default 3 seconds

// ✅ NEW: Track temp code usage per door (in ESP32 memory)
struct TempCodeDoorUsage {
    String code;      // The PIN code
    int doorNumber;   // Which door
    int uses;         // How many times used on this door
};

std::vector<TempCodeDoorUsage> tempCodeUsageTracker;

// Helper function to get/update usage for a specific code+door combo
int getTempCodeDoorUses(const String& code, int doorNumber) {
    for (const auto& usage : tempCodeUsageTracker) {
        if (usage.code == code && usage.doorNumber == doorNumber) {
            return usage.uses;
        }
    }
    return 0;  // Never used on this door
}

void incrementTempCodeDoorUses(const String& code, int doorNumber) {
    // Find existing entry
    for (auto& usage : tempCodeUsageTracker) {
        if (usage.code == code && usage.doorNumber == doorNumber) {
            usage.uses++;
            return;
        }
    }
    
    // Not found - create new entry
    TempCodeDoorUsage newUsage;
    newUsage.code = code;
    newUsage.doorNumber = doorNumber;
    newUsage.uses = 1;
    tempCodeUsageTracker.push_back(newUsage);
}

void clearTempCodeDoorUsage(const String& code) {
    // Remove all usage entries for this code (when code is reset)
    tempCodeUsageTracker.erase(
        std::remove_if(tempCodeUsageTracker.begin(), tempCodeUsageTracker.end(),
            [&code](const TempCodeDoorUsage& usage) { return usage.code == code; }),
        tempCodeUsageTracker.end()
    );
}

struct DoorConfig {
    String name;
    int relayPin;
    int unlockDuration;
    int rexPin;
    int readerLedPin;   // ✅ NEW
    int readerBeepPin;  // ✅ NEW
    WiegandData wiegand;
    String lastCredential;      // ✅ ADD THIS
    bool isUnlocked;            // ✅ ADD THIS
    unsigned long unlockUntil;  // ✅ ADD THIS
    
    // Emergency override
    String emergencyOverride;  // "lock", "unlock", or ""
    
    // Schedule tracking
    String currentScheduleMode; // "unlock", "controlled", "locked"
    bool scheduledUnlock;       // True if unlocked by schedule
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

DynamicJsonDocument usersDB(16384);  // 16KB for user database
DynamicJsonDocument doorSchedulesDB(8192);  // 8KB for door schedules
DynamicJsonDocument tempCodesDB(4096);  // 4KB for temp codes
DynamicJsonDocument userSchedulesDB(4096);  // 4KB for user schedules

unsigned long lastHeartbeat = 0;
unsigned long lastScheduleCheck = 0;
unsigned long lastEmergencyCheck = 0;
unsigned long lastKeypadTimeoutCheck = 0;
unsigned long lastLogRetry = 0;  // ✅ NEW: Track log send attempts
bool controllerOnline = false;

String keypadBuffer = "";
unsigned long keypadLastKey = 0;
int currentKeypadDoor = -1;

unsigned long lastWiFiCheck = 0;
int wifiReconnectAttempts = 0;

// Wiegand ISR handlers
WiegandData* door1Wiegand = nullptr;
WiegandData* door2Wiegand = nullptr;

// ===============================================================
// NEW: LIVE LOG FUNCTIONS
// ===============================================================

void addLiveLog(String message) {
    // Add timestamp
    String logEntry = getTimestamp() + " | " + message;
    
    // Add to circular buffer
    liveLogBuffer[liveLogIndex] = logEntry;
    liveLogIndex = (liveLogIndex + 1) % LIVE_LOG_BUFFER_SIZE;
    liveLogCounter++;
    
    // Also print to serial
    Serial.println(message);
}

String getLiveLogsJSON() {
    DynamicJsonDocument doc(8192);
    JsonArray logs = doc.createNestedArray("logs");
    
    // Add logs in reverse order (newest first)
    for (int i = 0; i < LIVE_LOG_BUFFER_SIZE; i++) {
        int idx = (liveLogIndex - 1 - i + LIVE_LOG_BUFFER_SIZE) % LIVE_LOG_BUFFER_SIZE;
        if (liveLogBuffer[idx].length() > 0) {
            logs.add(liveLogBuffer[idx]);
        }
    }
    
    doc["count"] = liveLogCounter;
    
    String output;
    serializeJson(doc, output);
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

void readerBeepSuccess(int doorNumber) {
    int beepPin = doors[doorNumber - 1].readerBeepPin;
    digitalWrite(beepPin, HIGH);
    delay(READER_BEEP_SUCCESS_MS);
    digitalWrite(beepPin, LOW);
    delay(50);
    digitalWrite(beepPin, HIGH);
    delay(READER_BEEP_SUCCESS_MS);
    digitalWrite(beepPin, LOW);
}

void readerBeepError(int doorNumber) {
    int beepPin = doors[doorNumber - 1].readerBeepPin;
    digitalWrite(beepPin, HIGH);
    delay(READER_BEEP_ERROR_MS);
    digitalWrite(beepPin, LOW);
}

void readerLedSuccess(int doorNumber) {
    int ledPin = doors[doorNumber - 1].readerLedPin;
    digitalWrite(ledPin, HIGH);
    delay(READER_LED_SUCCESS_MS);
    digitalWrite(ledPin, LOW);
}

void readerLedError(int doorNumber) {
    int ledPin = doors[doorNumber - 1].readerLedPin;
    // Blink LED for error
    for (int i = 0; i < 3; i++) {
        digitalWrite(ledPin, HIGH);
        delay(200);
        digitalWrite(ledPin, LOW);
        delay(200);
    }
}

void readerFeedbackSuccess(int doorNumber) {
    readerBeepSuccess(doorNumber);
    readerLedSuccess(doorNumber);
}

void readerFeedbackError(int doorNumber) {
    readerBeepError(doorNumber);
    readerLedError(doorNumber);
}

// ===============================================================
// UTILITY FUNCTIONS
// ===============================================================

void beep(int duration = 100) {
    digitalWrite(BEEPER, HIGH);
    delay(duration);
    digitalWrite(BEEPER, LOW);
}

void beepSuccess() {
    beep(100);
    delay(50);
    beep(100);
}

void beepError() {
    beep(500);
}

void beepEmergency() {
    // Triple beep for emergency
    for (int i = 0; i < 3; i++) {
        beep(200);
        delay(100);
    }
}

void blinkLED(int times = 1) {
    for (int i = 0; i < times; i++) {
        digitalWrite(LED_STATUS, HIGH);
        delay(100);
        digitalWrite(LED_STATUS, LOW);
        delay(100);
    }
}

String getTimestamp() {
    time_t now = time(nullptr);
    struct tm timeinfo;
    if (!getLocalTime(&timeinfo)) {
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
    if (!getLocalTime(&timeinfo)) {
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
    if (getLocalTime(&timeinfo)) {
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
    if (!getLocalTime(&timeinfo)) {
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
        delay(10);
    }
    
    addLiveLog("⏱️  WiFi Portal timeout - restarting...");
    ESP.restart();
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
    
    String url = "http://" + config.controllerIP + ":" + String(config.controllerPort) + "/api/heartbeat";
    
    DynamicJsonDocument doc(256);
    doc["ip_address"] = WiFi.localIP().toString();
    doc["board_name"] = config.boardName;
    
    String payload;
    serializeJson(doc, payload);
    
    http.begin(url);
    http.addHeader("Content-Type", "application/json");
    http.setTimeout(5000);
    
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
    
    String url = "http://" + config.controllerIP + ":" + String(config.controllerPort) + "/api/access-log";
    
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
    
    addLiveLog("📤 Sending log to " + url);
    
    http.begin(url);
    http.addHeader("Content-Type", "application/json");
    http.setTimeout(10000);  // Increased from 3000 to 10000ms
    
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

void sendQueuedLogs() {
    if (logQueue.empty()) return;
    
    addLiveLog("📤 Sending " + String(logQueue.size()) + " queued logs...");
    
    for (auto it = logQueue.begin(); it != logQueue.end(); ) {
        if (sendAccessLog(*it)) {
            it = logQueue.erase(it);
        } else {
            break;
        }
    }
}

bool sendTempCodeUsage(const String& code, int currentUses) {
    if (config.controllerIP.length() == 0) return false;
    
    String url = "http://" + config.controllerIP + ":" + String(config.controllerPort) + "/api/temp-code-usage";
    
    DynamicJsonDocument doc(256);
    doc["code"] = code;
    doc["current_uses"] = currentUses;
    
    String payload;
    serializeJson(doc, payload);
    
    addLiveLog("🎫 Sending temp code usage update...");
    
    http.begin(url);
    http.addHeader("Content-Type", "application/json");
    http.setTimeout(5000);
    
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
            if (!user["active"].as<bool>()) continue;
            
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
            
            // ✅ Send door ID to server for server-side tracking
            if (config.controllerIP.length() > 0) {
                sendTempCodeUsage(credential, doorNumber);
            }
            
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
    
    addLiveLog("  User: " + result.userName);
    addLiveLog("  Result: " + String(result.granted ? "✅ GRANTED" : "❌ DENIED"));
    addLiveLog("  Reason: " + result.reason);
    
    AccessLog log;
    log.timestamp = getTimestamp();
    log.doorNumber = doorNumber;
    log.userName = result.userName;
    log.credential = credential;
    log.credentialType = result.isTempCode ? "temp_code" : credType;  // ✅ Mark as temp_code
    log.granted = result.granted;
    log.reason = result.reason;
    
    if (result.granted) {
        unlockDoor(doorNumber);
        readerFeedbackSuccess(doorNumber);
    } else {
        beepError();
        readerFeedbackError(doorNumber);
    }
    
    // ✅ ALWAYS try to send immediately (don't wait for heartbeat)
    bool logSent = false;
    
    if (WiFi.status() == WL_CONNECTED && config.controllerIP.length() > 0) {
        logSent = sendAccessLog(log);
    }
    
    // Only queue if send failed
    if (!logSent) {
        if (logQueue.size() < LOG_QUEUE_MAX) {
            logQueue.push_back(log);
            addLiveLog("📋 Log queued (" + String(logQueue.size()) + "/" + String(LOG_QUEUE_MAX) + ")");
        } else {
            logQueue.erase(logQueue.begin());
            logQueue.push_back(log);
            addLiveLog("⚠️ Log queue full - dropped oldest log");
        }
    }
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
        html += "<table>";
        html += "<tr><td><b>Board Name:</b></td><td>" + config.boardName + "</td></tr>";
        html += "<tr><td><b>IP Address:</b></td><td>" + WiFi.localIP().toString() + "</td></tr>";
        html += "<tr><td><b>MAC Address:</b></td><td>" + config.macAddress + "</td></tr>";
        html += "<tr><td><b>Controller IP:</b></td><td>" + (config.controllerIP.length() > 0 ? config.controllerIP : "Not configured") + "</td></tr>";
        html += "<tr><td><b>Users Loaded:</b></td><td>" + String(usersDB.containsKey("users") ? usersDB["users"].size() : 0) + "</td></tr>";
        html += "<tr><td><b>Queued Logs:</b></td><td>" + String(logQueue.size()) + "/" + String(LOG_QUEUE_MAX) + "</td></tr>";
        html += "<tr><td><b>Emergency Mode:</b></td><td style='color:" + emergencyColor + "'><b>" + emergencyStatus + "</b></td></tr>";
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
    
    // API: Sync users database and door schedules
    server.on("/api/sync", HTTP_POST, []() {
        String jsonData = server.arg("plain");
        
        addLiveLog("=== SYNC REQUEST RECEIVED ===");
        addLiveLog("Data length: " + String(jsonData.length()) + " bytes");
        
        DynamicJsonDocument syncDoc(20480);
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

// ✅ NEW: Load unlock durations from sync
if (syncDoc.containsKey("unlock_durations")) {
    JsonObject durations = syncDoc["unlock_durations"];
    
    if (durations.containsKey("door1")) {
        door1UnlockDuration = durations["door1"].as<int>();
        addLiveLog("⏱️ Door 1 unlock: " + String(door1UnlockDuration) + "ms");
    }
    
    if (durations.containsKey("door2")) {
        door2UnlockDuration = durations["door2"].as<int>();
        addLiveLog("⏱️ Door 2 unlock: " + String(door2UnlockDuration) + "ms");
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
// SETUP
// ===============================================================

void setup() {
    Serial.begin(115200);
    delay(1000);
    
    Serial.println("\n\n=======================================================");
    Serial.println("🔐 ACCESS CONTROL SYSTEM - ESP32 FIRMWARE v3.2");
    Serial.println("   With Live Logs & Raw Wiegand Data Viewer");
    Serial.println("=======================================================");
    
    addLiveLog("=== SYSTEM BOOT ===");
    
    if (!SPIFFS.begin(true)) {
        addLiveLog("❌ SPIFFS initialization failed");
    } else {
        addLiveLog("✅ SPIFFS initialized");
    }
    
    loadConfig();
    
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

    // NOTE: Wiegand interrupts are attached AFTER WiFi connection
    // to prevent interference during WiFi negotiation
    addLiveLog("✅ GPIO initialized (interrupts pending)");

    if (!config.configured || config.wifiSSID.length() == 0) {
        addLiveLog("⚠️  No WiFi configuration - starting setup portal");
        startWiFiManager();
    }

    if (connectWiFi()) {
        // Attach Wiegand interrupts AFTER WiFi is connected
        // This prevents interference during WiFi negotiation
        attachInterrupt(digitalPinToInterrupt(WIEGAND_D0_DOOR1), door1_D0_ISR, FALLING);
        attachInterrupt(digitalPinToInterrupt(WIEGAND_D1_DOOR1), door1_D1_ISR, FALLING);
        attachInterrupt(digitalPinToInterrupt(WIEGAND_D0_DOOR2), door2_D0_ISR, FALLING);
        attachInterrupt(digitalPinToInterrupt(WIEGAND_D1_DOOR2), door2_D1_ISR, FALLING);
        addLiveLog("✅ Wiegand interrupts attached");

        loadUsersDB();
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
        addLiveLog("⚠️  WiFi connection failed - starting setup portal");
        startWiFiManager();
    }
    
    addLiveLog("=======================================================");
    addLiveLog("✅ System ready!");
    addLiveLog("=======================================================");
    
    beepSuccess();
}

// ===============================================================
// MAIN LOOP
// ===============================================================

void loop() {
    unsigned long now = millis();
    
    
    // ✅ ADD THIS ENTIRE SECTION HERE:
    // ===============================================================
    // WiFi Watchdog - Auto-reconnect if disconnected
    // ===============================================================
    if (now - lastWiFiCheck >= 30000) {  // Check every 30 seconds
        lastWiFiCheck = now;
        
        if (WiFi.status() != WL_CONNECTED) {
            // WiFi is DOWN!
            wifiReconnectAttempts++;
            addLiveLog("⚠️  WiFi DISCONNECTED! (Attempt " + String(wifiReconnectAttempts) + "/10)");
            
            // Try to reconnect
            addLiveLog("🔄 Attempting WiFi reconnection...");
            WiFi.disconnect();
            WiFi.begin(config.wifiSSID.c_str(), config.wifiPassword.c_str());
            
            // Wait up to 10 seconds for connection
            int attempts = 0;
            while (WiFi.status() != WL_CONNECTED && attempts < 20) {
                delay(500);
                Serial.print(".");
                blinkLED(1);
                attempts++;
            }
            
            if (WiFi.status() == WL_CONNECTED) {
                // WiFi RECONNECTED!
                addLiveLog("✅ WiFi reconnected successfully!");
                addLiveLog("📍 IP Address: " + WiFi.localIP().toString());
                wifiReconnectAttempts = 0;
                
                // Try to re-announce to controller
                if (config.controllerIP.length() > 0) {
                    addLiveLog("📢 Re-announcing to controller...");
                    delay(2000);
                    if (announceToController()) {
                        addLiveLog("✅ Controller reconnected!");
                    } else {
                        addLiveLog("⚠️  Controller still offline (WiFi OK)");
                    }
                }
            } else {
                // WiFi reconnection FAILED
                addLiveLog("❌ WiFi reconnection failed (attempt " + String(wifiReconnectAttempts) + "/10)");
                
                if (wifiReconnectAttempts >= 10) {
                    // After 10 failed attempts (5 minutes), start AP mode
                    addLiveLog("🚨 WiFi FAILED 10 times - Starting AP configuration portal");
                    addLiveLog("⚠️  Access control will continue offline with last synced data");
                    
                    // Start AP mode for reconfiguration
                    startWiFiManager();
                }
            }
        } else {
            // WiFi is CONNECTED
            if (wifiReconnectAttempts > 0) {
                wifiReconnectAttempts = 0;
            }
        }
    }
    // ===============================================================
    // END OF WIFI WATCHDOG
    // ===============================================================
    
    server.handleClient();
    checkWiegandData();
    checkDoorLocks();
    
    
    
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
    
    if (digitalRead(doors[0].rexPin) == LOW) {
        addLiveLog("🚪 REX button pressed - Door 1");
        unlockDoor(1);
        delay(500);
    }
    
    if (digitalRead(doors[1].rexPin) == LOW) {
        addLiveLog("🚪 REX button pressed - Door 2");
        unlockDoor(2);
        delay(500);
    }
    
    if (now - lastHeartbeat >= HEARTBEAT_INTERVAL) {
        lastHeartbeat = now;
        
        // Only try heartbeat if WiFi is connected
        if (WiFi.status() == WL_CONNECTED) {
            if (sendHeartbeat()) {
                // Controller is ONLINE
                if (!logQueue.empty()) {
                    sendQueuedLogs();
                }
            }
            // If heartbeat fails, controller is offline but WiFi is OK
            // This is normal - just keep trying every 60s
        } else {
            // WiFi is down - skip heartbeat (watchdog will handle WiFdog)
            addLiveLog("⏭️  Skipping heartbeat - WiFi disconnected");
        }
    }
    
    // ✅ NEW: Try to send queued logs every 5 seconds (independent of heartbeat)
    if (now - lastLogRetry >= 5000) {  // Every 5 seconds
        lastLogRetry = now;
        
        if (!logQueue.empty() && WiFi.status() == WL_CONNECTED) {
            sendQueuedLogs();
        }
    }
    
    delay(10);
}
