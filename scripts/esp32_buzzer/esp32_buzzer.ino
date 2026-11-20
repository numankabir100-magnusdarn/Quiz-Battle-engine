/* ================================================================
   EEECI FA'26 — Module 06: EEE Brain Battle
   ESP32 Dual Buzzer Firmware (Production Tested)

   WIFI:
   SSID       : main
   PASSWORD   : 11223344
   SERVER IP  : Windows Hotspot Gateway (192.168.137.1)
   SERVER PORT: 4210
   LOCAL PORT : 4211

   HARDWARE PINS:
   Team A Button : GPIO 13  (INPUT_PULLUP, pressed = LOW)
   Team B Button : GPIO 14  (INPUT_PULLUP, pressed = LOW)
   Buzzer 1      : GPIO 25  (Sound Output)
   Buzzer 2      : GPIO 26  (Sound Output)

   FAIRNESS:
   Debounce   = 25 ms
   Tie window = 20 ms
================================================================ */

#include <WiFi.h>
#include <WiFiUdp.h>

// ================================================================
// WIFI CONFIGURATION
// ================================================================

const char* WIFI_SSID     = "main";
const char* WIFI_PASSWORD = "11223344";

IPAddress serverIP(192, 168, 137, 1);

const uint16_t SERVER_PORT = 4210; // Server listening port
const uint16_t LOCAL_PORT  = 4211; // ESP32 listening port

WiFiUDP udp;

bool udpStarted = false;
bool wasConnected = false;

unsigned long lastPingTime = 0;
unsigned long lastReconnectTime = 0;

const unsigned long PING_INTERVAL      = 3000;
const unsigned long RECONNECT_INTERVAL = 5000;

// ================================================================
// PIN CONFIGURATION (YOUR EXACT PINS)
// ================================================================

#define PIN_BUTTON_A 13
#define PIN_BUTTON_B 14

#define PIN_BUZZER_1 25
#define PIN_BUZZER_2 26

// ================================================================
// BUTTON TIMING
// ================================================================

const uint32_t DEBOUNCE_US   = 25000; // 25ms
const uint32_t TIE_WINDOW_US = 20000; // 20ms

// ================================================================
// GAME STATE
// ================================================================

volatile bool candidateA = false;
volatile bool candidateB = false;

volatile uint32_t timeA = 0;
volatile uint32_t timeB = 0;

volatile bool roundLocked = false;
volatile bool resultFinalized = false;

volatile bool allowA = true;
volatile bool allowB = true;

// ================================================================
// BUZZER STATE (Both Buzzers Fire Together)
// ================================================================

inline void buzzerOn() {
  digitalWrite(PIN_BUZZER_1, HIGH);
  digitalWrite(PIN_BUZZER_2, HIGH);
}

inline void buzzerOff() {
  digitalWrite(PIN_BUZZER_1, LOW);
  digitalWrite(PIN_BUZZER_2, LOW);
}

// ================================================================
// SOUND ENGINE
// ================================================================

void soundBeep(int frequencyHz, int durationMs) {
  unsigned long start = millis();
  unsigned long halfPeriodMicros = 1000000UL / (frequencyHz * 2UL);

  while (millis() - start < (unsigned long)durationMs) {
    buzzerOn();
    delayMicroseconds(halfPeriodMicros);
    buzzerOff();
    delayMicroseconds(halfPeriodMicros);
  }
  buzzerOff();
  delay(15);
}

void soundStartup() {
  soundBeep(800, 80);
  delay(30);
  soundBeep(1200, 80);
  delay(30);
  soundBeep(1600, 140);
}

void soundTeamAHit() {
  soundBeep(1000, 220); // 1 Solid Loud Beep
}

void soundTeamBHit() {
  soundBeep(1600, 90);  // 2 Rapid High Beeps
  delay(40);
  soundBeep(1600, 110);
}

void soundTie() {
  soundBeep(800, 120);
  delay(50);
  soundBeep(800, 120);
}

void soundReset() {
  soundBeep(2000, 50);  // Crisp double chirp for Unlock / Ready
  delay(30);
  soundBeep(2400, 70);
}

void soundPassOver() {
  soundBeep(450, 160);  // Low warning tone for pass-over (-5 penalty)
}

void soundTestPattern() {
  for (int i = 0; i < 3; i++) {
    soundBeep(1400, 60);
    delay(40);
  }
}

// ================================================================
// SEND UDP MESSAGE
// ================================================================

void sendCommand(const char* command) {
  if (WiFi.status() != WL_CONNECTED || !udpStarted) {
    return;
  }
  udp.beginPacket(serverIP, SERVER_PORT);
  udp.print(command);
  udp.endPacket();

  Serial.print("[UDP TX] -> ");
  Serial.println(command);
}

// ================================================================
// BUTTON INTERRUPTS
// ================================================================

void IRAM_ATTR buttonA_ISR() {
  if (!resultFinalized && allowA && !candidateA) {
    timeA = micros();
    candidateA = true;
    roundLocked = true;
  }
}

void IRAM_ATTR buttonB_ISR() {
  if (!resultFinalized && allowB && !candidateB) {
    timeB = micros();
    candidateB = true;
    roundLocked = true;
  }
}

// ================================================================
// RESET GAME (Re-arms buzzers for the next question)
// ================================================================

void resetGame(bool enableA, bool enableB) {
  noInterrupts();
  candidateA = false;
  candidateB = false;
  timeA = 0;
  timeB = 0;
  roundLocked = false;
  resultFinalized = false;
  allowA = enableA;
  allowB = enableB;
  interrupts();

  buzzerOff();

  Serial.println("[STATE] Round UNLOCKED (Armed for Next Question)");
  if (enableA && enableB) {
    Serial.println("[STATE] Both teams enabled");
  } else if (enableA) {
    Serial.println("[STATE] Only Team A enabled");
  } else if (enableB) {
    Serial.println("[STATE] Only Team B enabled");
  }
}

// ================================================================
// PROCESS BUTTON PRESSES
// ================================================================

void processButtons() {
  bool aDetected;
  bool bDetected;
  uint32_t tA;
  uint32_t tB;
  bool finalized;

  noInterrupts();
  aDetected = candidateA;
  bDetected = candidateB;
  tA = timeA;
  tB = timeB;
  finalized = resultFinalized;
  interrupts();

  if (finalized || (!aDetected && !bDetected)) {
    return;
  }

  uint32_t now = micros();
  uint32_t latestTime;

  if (aDetected && bDetected) {
    int32_t difference = (int32_t)(tA - tB);
    latestTime = (difference <= 0) ? tB : tA;
  } else {
    latestTime = aDetected ? tA : tB;
  }

  if ((uint32_t)(now - latestTime) < DEBOUNCE_US) {
    return;
  }

  // Physical pin verification
  bool aValid = aDetected && (digitalRead(PIN_BUTTON_A) == LOW);
  bool bValid = bDetected && (digitalRead(PIN_BUTTON_B) == LOW);

  int result = 0;

  if (aValid && bValid) {
    int32_t difference = (int32_t)(tA - tB);
    if (difference >= -(int32_t)TIE_WINDOW_US && difference <= (int32_t)TIE_WINDOW_US) {
      result = 3;  // TIE
    } else {
      result = (difference < 0) ? 1 : 2;
    }
  } else if (aValid) {
    result = 1;  // TEAM A
  } else if (bValid) {
    result = 2;  // TEAM B
  }

  noInterrupts();
  if (resultFinalized) {
    interrupts();
    return;
  }

  if (result != 0) {
    resultFinalized = true;
    roundLocked = true;
  } else {
    candidateA = false;
    candidateB = false;
    roundLocked = false;
  }
  interrupts();

  if (result == 1) {
    Serial.println("[BUZZ] TEAM A PRESSED FIRST!");
    sendCommand("TEAM_A");
    soundTeamAHit();
  } else if (result == 2) {
    Serial.println("[BUZZ] TEAM B PRESSED FIRST!");
    sendCommand("TEAM_B");
    soundTeamBHit();
  } else if (result == 3) {
    Serial.println("[BUZZ] TIE! BOTH TEAMS PRESSED!");
    sendCommand("TIE");
    soundTie();
  }
}

// ================================================================
// RECEIVE COMMANDS FROM SERVER (Robust Prefix-Insensitive Matching)
// ================================================================

void receiveServerCommands() {
  int packetSize = udp.parsePacket();
  if (packetSize <= 0) {
    return;
  }

  char buffer[64];
  int len = udp.read(buffer, sizeof(buffer) - 1);
  if (len <= 0) {
    return;
  }
  buffer[len] = '\0';

  // Strip trailing whitespace, newlines, and carriage returns
  while (len > 0 && (buffer[len - 1] == '\r' || buffer[len - 1] == '\n' || buffer[len - 1] == ' ')) {
    buffer[--len] = '\0';
  }

  Serial.print("[UDP RX] <- ");
  Serial.println(buffer);

  // Use strstr so it matches both plain ("RESET") and prefixed ("EEECI:RESET")
  if (strstr(buffer, "RESET") != NULL) {
    resetGame(true, true);
    soundReset();
  } else if (strstr(buffer, "TEST") != NULL) {
    Serial.println("[STATE] Buzzer test triggered by server");
    sendCommand("ACK");
    soundTestPattern();
  } else if (strstr(buffer, "PASS_A") != NULL) {
    resetGame(true, false);
    soundPassOver();
  } else if (strstr(buffer, "PASS_B") != NULL) {
    resetGame(false, true);
    soundPassOver();
  } else if (strstr(buffer, "PONG") != NULL) {
    Serial.println("[STATE] Server connection confirmed (Heartbeat ACK)");
  }
}

// ================================================================
// WIFI MANAGEMENT
// ================================================================

void manageWiFi() {
  bool connected = (WiFi.status() == WL_CONNECTED);

  if (connected && !wasConnected) {
    Serial.println("\n[Wi-Fi] Connected successfully!");
    Serial.print("[Wi-Fi] ESP32 IP: ");
    Serial.println(WiFi.localIP());
    Serial.print("[Wi-Fi] Gateway (Server IP): ");
    Serial.println(WiFi.gatewayIP());

    serverIP = WiFi.gatewayIP();

    udp.begin(LOCAL_PORT);
    udpStarted = true;
    wasConnected = true;
    lastPingTime = millis();

    sendCommand("HELLO");
    soundStartup();
  }

  if (!connected) {
    if (wasConnected) {
      Serial.println("\n[Wi-Fi] Connection lost!");
      udp.stop();
      udpStarted = false;
      wasConnected = false;
    }

    if (millis() - lastReconnectTime >= RECONNECT_INTERVAL) {
      lastReconnectTime = millis();
      Serial.println("[Wi-Fi] Reconnecting...");
      WiFi.reconnect();
    }
  }
}

// ================================================================
// SETUP
// ================================================================

void setup() {
  Serial.begin(115200);
  delay(400);

  Serial.println();
  Serial.println("======================================");
  Serial.println(" EEECI FA'26 - EEE BRAIN BATTLE");
  Serial.println(" ESP32 DUAL BUZZER SYSTEM (PINS 13/14)");
  Serial.println("======================================");

  pinMode(PIN_BUTTON_A, INPUT_PULLUP);
  pinMode(PIN_BUTTON_B, INPUT_PULLUP);

  pinMode(PIN_BUZZER_1, OUTPUT);
  pinMode(PIN_BUZZER_2, OUTPUT);

  buzzerOff();

  // Test both buzzers right on boot so you know they are wired correctly
  Serial.println("[Buzzer] Self-test chirp on GPIO 25 & 26...");
  soundBeep(1000, 80);

  Serial.printf("[Wi-Fi] Connecting to '%s'...\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  attachInterrupt(digitalPinToInterrupt(PIN_BUTTON_A), buttonA_ISR, FALLING);
  attachInterrupt(digitalPinToInterrupt(PIN_BUTTON_B), buttonB_ISR, FALLING);
}

// ================================================================
// MAIN LOOP
// ================================================================

void loop() {
  // 1. Maintain Wi-Fi
  manageWiFi();

  // 2. Process incoming server commands
  if (WiFi.status() == WL_CONNECTED && udpStarted) {
    receiveServerCommands();

    // 3. Send heartbeat every 3 seconds
    if (millis() - lastPingTime >= PING_INTERVAL) {
      lastPingTime = millis();
      sendCommand("PING");
    }
  }

  // 4. Process contestant button presses
  processButtons();
}
