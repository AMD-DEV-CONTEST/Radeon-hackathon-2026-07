/*
 * ============================================================
 *  TamilVox — All-in-One Single ESP32 DevKit C
 *
 *  Everything on ONE ESP32:
 *    - INMP441 I2S Mic     → Voice input
 *    - SSD1306 OLED        → Display
 *    - MAX98357A I2S Amp   → Speaker output
 *    - Relay x3            → Light, Fan, AC control
 *    - BOOT button GPIO0   → Push to talk
 *
 *  Wiring Summary:
 *    OLED SDA  → GPIO21     OLED SCL  → GPIO22
 *    MIC WS    → GPIO15     MIC SCK   → GPIO14    MIC SD → GPIO32
 *    AMP LRC   → GPIO25     AMP BCLK  → GPIO26    AMP DIN → GPIO27
 *    RELAY LIGHT → GPIO33
 *    RELAY FAN   → GPIO19
 *    RELAY AC    → GPIO18
 *    BUTTON      → GPIO0 (built-in BOOT)
 *
 *  Libraries (Arduino Library Manager):
 *    - Adafruit SSD1306    by Adafruit
 *    - Adafruit GFX Library by Adafruit
 *    - ArduinoJson         by Benoit Blanchon (v6)
 *    - Base64              by Densaugeo
 *    - PubSubClient        by Nick O'Leary
 * ============================================================
 */

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <ArduinoJson.h>
#include <base64.hpp>
#include <PubSubClient.h>
#include <driver/i2s.h>
#include "tamilvox_config.h"

// MQTT Topics
const char* TOPIC_LIGHT   = "tamilvox/home/light";
const char* TOPIC_FAN     = "tamilvox/home/fan";
const char* TOPIC_AC      = "tamilvox/home/ac";
const char* TOPIC_STATUS  = "tamilvox/home/status";

// ─────────────────────────────────────────────
// PIN DEFINITIONS
// ─────────────────────────────────────────────

// OLED
#define OLED_SDA    21
#define OLED_SCL    22

// INMP441 Mic (I2S Port 0)
#define MIC_WS      15
#define MIC_SCK     14
#define MIC_SD      32

// MAX98357A Amp (I2S Port 1)
#define AMP_LRC     25
#define AMP_BCLK    26
#define AMP_DIN     27

// Relay pins (HIGH = relay OFF, LOW = relay ON for most modules)
#define RELAY_LIGHT 33
#define RELAY_FAN   19
#define RELAY_AC    18

// Button
#define BUTTON_PIN   0   // Built-in BOOT button, active LOW

// ─────────────────────────────────────────────
// CONSTANTS
// ─────────────────────────────────────────────
#define SCREEN_WIDTH    128
#define SCREEN_HEIGHT    64
#define OLED_ADDR      0x3C
#define OLED_RESET       -1

#define SAMPLE_RATE    16000
#define RECORD_SECONDS     3
#define I2S_PORT_MIC   I2S_NUM_0
#define I2S_PORT_AMP   I2S_NUM_1
#define DMA_BUF_SIZE     512
#define WAV_HEADER_SIZE   44
#define BITS_PER_SAMPLE   16

const int TOTAL_SAMPLES = SAMPLE_RATE * RECORD_SECONDS;

// ─────────────────────────────────────────────
// GLOBALS
// ─────────────────────────────────────────────
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

WiFiClientSecure wifiSecure;
PubSubClient     mqttClient(wifiSecure);

int16_t* audioBuffer = nullptr;
uint8_t* wavBuffer = nullptr;
int      wavSize   = 0;

// Device states
bool lightState = false;
bool fanState   = false;
bool acState    = false;


// ─────────────────────────────────────────────
// RELAY HELPERS
// ─────────────────────────────────────────────
void relayOn(int pin)  { digitalWrite(pin, LOW);  }
void relayOff(int pin) { digitalWrite(pin, HIGH); }

void controlLight(bool on) {
    lightState = on;
    on ? relayOn(RELAY_LIGHT) : relayOff(RELAY_LIGHT);
    Serial.printf("[RELAY] Light %s\n", on ? "ON" : "OFF");
}

void controlFan(bool on) {
    fanState = on;
    on ? relayOn(RELAY_FAN) : relayOff(RELAY_FAN);
    Serial.printf("[RELAY] Fan %s\n", on ? "ON" : "OFF");
}

void controlAC(bool on) {
    acState = on;
    on ? relayOn(RELAY_AC) : relayOff(RELAY_AC);
    Serial.printf("[RELAY] AC %s\n", on ? "ON" : "OFF");
}

void allOff() {
    controlLight(false);
    controlFan(false);
    controlAC(false);
    Serial.println("[RELAY] All OFF");
}


// ─────────────────────────────────────────────
// OLED HELPERS
// ─────────────────────────────────────────────
void oledShow(const char* l1, const char* l2 = "",
              const char* l3 = "", const char* l4 = "") {
    display.clearDisplay();
    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(0,  0); display.println(l1);
    display.setCursor(0, 16); display.println(l2);
    display.setCursor(0, 32); display.println(l3);
    display.setCursor(0, 48); display.println(l4);
    display.display();
}

void oledTitle(const char* title, const char* sub = "") {
    display.clearDisplay();
    display.setTextSize(2);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(0, 0);
    display.println(title);
    display.setTextSize(1);
    display.setCursor(0, 20);
    display.println(sub);
    display.display();
}

void oledStatus() {
    display.clearDisplay();
    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(0, 0);  display.println("Device Status:");
    display.setCursor(0, 14); display.printf("Light: %s", lightState ? "ON " : "OFF");
    display.setCursor(0, 26); display.printf("Fan:   %s", fanState   ? "ON " : "OFF");
    display.setCursor(0, 38); display.printf("AC:    %s", acState    ? "ON " : "OFF");
    display.setCursor(0, 52); display.println("BOOT = speak");
    display.display();
}

void oledRecording(int frame) {
    display.clearDisplay();
    display.setTextSize(2);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(0, 0);  display.println("Recording");
    display.setTextSize(1);
    display.setCursor(0, 20); display.println("Speak Tamil/English");
    String dots = "";
    for (int i = 0; i < (frame % 4); i++) dots += ".";
    display.setCursor(0, 50); display.println(dots);
    display.display();
}

void oledChat(const char* label, const char* text) {
    display.clearDisplay();
    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(0, 0);  display.println(label);
    String t = String(text);
    display.setCursor(0, 12); display.println(t.substring(0, 21));
    display.setCursor(0, 22); display.println(t.substring(21, 42));
    display.setCursor(0, 32); display.println(t.substring(42, 63));
    display.display();
}

void oledCommand(const char* device, const char* cmd, bool state) {
    display.clearDisplay();
    display.setTextSize(2);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(0, 0);
    display.println(device);
    display.setCursor(0, 20);
    display.println(state ? "ON" : "OFF");
    display.setTextSize(1);
    display.setCursor(0, 50);
    display.println(cmd);
    display.display();
}


// ─────────────────────────────────────────────
// WAV HEADER
// ─────────────────────────────────────────────
void buildWavHeader(uint8_t* h, int dataSize) {
    int fileSize  = dataSize + WAV_HEADER_SIZE - 8;
    int byteRate  = SAMPLE_RATE * BITS_PER_SAMPLE / 8;
    int blockAlign = BITS_PER_SAMPLE / 8;
    memcpy(h,    "RIFF", 4);
    h[4]=(fileSize)&0xFF; h[5]=(fileSize>>8)&0xFF;
    h[6]=(fileSize>>16)&0xFF; h[7]=(fileSize>>24)&0xFF;
    memcpy(h+8,  "WAVE", 4);
    memcpy(h+12, "fmt ", 4);
    h[16]=16; h[17]=0; h[18]=0; h[19]=0;
    h[20]=1;  h[21]=0;
    h[22]=1;  h[23]=0;
    h[24]=(SAMPLE_RATE)&0xFF; h[25]=(SAMPLE_RATE>>8)&0xFF;
    h[26]=(SAMPLE_RATE>>16)&0xFF; h[27]=(SAMPLE_RATE>>24)&0xFF;
    h[28]=(byteRate)&0xFF; h[29]=(byteRate>>8)&0xFF;
    h[30]=(byteRate>>16)&0xFF; h[31]=(byteRate>>24)&0xFF;
    h[32]=blockAlign; h[33]=0;
    h[34]=BITS_PER_SAMPLE; h[35]=0;
    memcpy(h+36, "data", 4);
    h[40]=(dataSize)&0xFF; h[41]=(dataSize>>8)&0xFF;
    h[42]=(dataSize>>16)&0xFF; h[43]=(dataSize>>24)&0xFF;
}




// ─────────────────────────────────────────────
// I2S MIC SETUP
// ─────────────────────────────────────────────
void setupMic() {
    i2s_config_t cfg = {
        .mode                 = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
        .sample_rate          = SAMPLE_RATE,
        .bits_per_sample      = I2S_BITS_PER_SAMPLE_32BIT,
        .channel_format       = I2S_CHANNEL_FMT_ONLY_LEFT,
        .communication_format = I2S_COMM_FORMAT_STAND_I2S,
        .intr_alloc_flags     = ESP_INTR_FLAG_LEVEL1,
        .dma_buf_count        = 4,
        .dma_buf_len          = DMA_BUF_SIZE,
        .use_apll             = false
    };
    i2s_pin_config_t pins = {
        .bck_io_num   = MIC_SCK,
        .ws_io_num    = MIC_WS,
        .data_out_num = I2S_PIN_NO_CHANGE,
        .data_in_num  = MIC_SD
    };
    i2s_driver_install(I2S_PORT_MIC, &cfg, 0, NULL);
    i2s_set_pin(I2S_PORT_MIC, &pins);
}


// ─────────────────────────────────────────────
// I2S AMP SETUP
// ─────────────────────────────────────────────
void setupAmp() {
    i2s_config_t cfg = {
        .mode                 = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
        .sample_rate          = SAMPLE_RATE,
        .bits_per_sample      = I2S_BITS_PER_SAMPLE_16BIT,
        .channel_format       = I2S_CHANNEL_FMT_RIGHT_LEFT,
        .communication_format = I2S_COMM_FORMAT_STAND_I2S,
        .intr_alloc_flags     = ESP_INTR_FLAG_LEVEL1,
        .dma_buf_count        = 4,
        .dma_buf_len          = DMA_BUF_SIZE,
        .use_apll             = false
    };
    i2s_pin_config_t pins = {
        .bck_io_num   = AMP_BCLK,
        .ws_io_num    = AMP_LRC,
        .data_out_num = AMP_DIN,
        .data_in_num  = I2S_PIN_NO_CHANGE
    };
    i2s_driver_install(I2S_PORT_AMP, &cfg, 0, NULL);
    i2s_set_pin(I2S_PORT_AMP, &pins);
}


// ─────────────────────────────────────────────
// RECORD AUDIO
// ─────────────────────────────────────────────
void recordAudio() {
    if (audioBuffer) {
        free(audioBuffer);
        audioBuffer = nullptr;
    }
    audioBuffer = (int16_t*)malloc(TOTAL_SAMPLES * sizeof(int16_t));
    if (!audioBuffer) {
        oledShow("Memory Error!", "Audio buffer fail");
        wavSize = 0;
        return;
    }

    int32_t raw[DMA_BUF_SIZE];
    int samplesRead = 0;
    size_t bytesRead = 0;
    int frame = 0;

    while (samplesRead < TOTAL_SAMPLES) {
        oledRecording(frame++);
        int toRead = min((int)DMA_BUF_SIZE, TOTAL_SAMPLES - samplesRead);
        i2s_read(I2S_PORT_MIC, raw, toRead * sizeof(int32_t), &bytesRead, portMAX_DELAY);
        int got = bytesRead / sizeof(int32_t);
        for (int i = 0; i < got && samplesRead < TOTAL_SAMPLES; i++) {
            audioBuffer[samplesRead++] = (int16_t)(raw[i] >> 16);
        }
    }

    int dataSize = TOTAL_SAMPLES * sizeof(int16_t);
    wavSize = WAV_HEADER_SIZE + dataSize;
    if (wavBuffer) free(wavBuffer);
    wavBuffer = (uint8_t*)malloc(wavSize);
    if (!wavBuffer) { oledShow("Memory Error!", "Restart ESP32"); return; }
    buildWavHeader(wavBuffer, dataSize);
    memcpy(wavBuffer + WAV_HEADER_SIZE, audioBuffer, dataSize);
    free(audioBuffer);
    audioBuffer = nullptr;

    oledShow("Processing...", "Sending to AI", "server...");
}


// ─────────────────────────────────────────────
// PLAY AUDIO
// ─────────────────────────────────────────────
void playAudio(uint8_t* pcm, int len) {
    size_t written = 0;
    int offset = 0;
    while (offset < len) {
        int chunk = min(DMA_BUF_SIZE * 2, len - offset);
        i2s_write(I2S_PORT_AMP, pcm + offset, chunk, &written, portMAX_DELAY);
        offset += chunk;
    }
}


// ─────────────────────────────────────────────
// MQTT CALLBACKS
// ─────────────────────────────────────────────
void mqttCallback(char* topic, byte* payload, unsigned int length) {
    char msg[256];
    unsigned int copyLen = min(length, (unsigned int)255);
    memcpy(msg, payload, copyLen);
    msg[copyLen] = '\0';
    Serial.printf("[MQTT] %s → %s\n", topic, msg);
    // Status messages from server — can extend here
}

void connectMqtt() {
    if (mqttClient.connected()) return;
    Serial.print("[MQTT] Connecting...");
    String cid = "TamilVox-" + String(random(0xffff), HEX);
    if (mqttClient.connect(cid.c_str(), MQTT_USER, MQTT_PASSWORD)) {
        Serial.println(" Connected!");
        mqttClient.subscribe(TOPIC_STATUS);
    } else {
        Serial.printf(" Failed rc=%d\n", mqttClient.state());
    }
}


// ─────────────────────────────────────────────
// HANDLE SERVER RESPONSE
// ─────────────────────────────────────────────
void handleResponse(String& jsonStr) {
    DynamicJsonDocument doc(1024 * 60);
    if (deserializeJson(doc, jsonStr) != DeserializationError::Ok) {
        oledShow("JSON Error", "Check server log"); return;
    }

    const char* userText   = doc["user_text"]  | "...";
    const char* replyText  = doc["reply_text"] | "...";
    const char* audioB64   = doc["audio_b64"]  | "";
    bool        isCommand  = doc["is_command"] | false;
    const char* device     = doc["device"]     | "";
    const char* command    = doc["command"]    | "";

    Serial.printf("[RESULT] User:  %s\n", userText);
    Serial.printf("[RESULT] Reply: %s\n", replyText);
    Serial.printf("[RESULT] Cmd:   %s %s\n", device, command);

    // ── Execute relay command locally ──
    if (isCommand && strlen(device) > 0) {
        String dev(device);
        String cmd(command);
        bool turnOn = (cmd == "ON" || cmd.startsWith("SPEED_") || cmd.startsWith("TEMP_"));

        if (dev == "light") {
            controlLight(turnOn);
            oledCommand("LIGHT", command, turnOn);
        } else if (dev == "fan") {
            controlFan(turnOn);
            oledCommand("FAN", command, turnOn);
        } else if (dev == "ac") {
            controlAC(turnOn);
            oledCommand("AC", command, turnOn);
        } else if (dev == "all" && cmd == "OFF") {
            allOff();
            oledShow("ALL", "Turned OFF", "", "");
        }
        delay(1500);
    } else {
        // General conversation — show on OLED
        oledChat("You said:", userText);
        delay(2000);
        oledChat("AI Reply:", replyText);
        delay(500);
    }

    // ── Play Tamil voice reply ──
    if (strlen(audioB64) > 0) {
        int audioLen = decode_base64_length((unsigned char*)audioB64, strlen(audioB64));
        uint8_t* audioBuf = (uint8_t*)malloc(audioLen);
        if (audioBuf) {
            decode_base64((unsigned char*)audioB64, strlen(audioB64), (unsigned char*)audioBuf);
            oledShow("Playing...", replyText, "", "");
            playAudio(audioBuf + WAV_HEADER_SIZE, audioLen - WAV_HEADER_SIZE);
            free(audioBuf);
        }
    }
}


// ─────────────────────────────────────────────
// SEND TO SERVER
// ─────────────────────────────────────────────
void sendToServer() {
    if (WiFi.status() != WL_CONNECTED) {
        oledShow("WiFi Error!", "Reconnecting...");
        WiFi.reconnect(); delay(3000); return;
    }
    if (!wavBuffer || wavSize <= 0) {
        oledShow("Audio Error!", "No WAV recorded");
        return;
    }

    WiFiClient client;
    client.setTimeout(90);
    if (!client.connect(SERVER_HOST, SERVER_PORT)) {
        free(wavBuffer);
        wavBuffer = nullptr;
        wavSize = 0;
        oledShow("Server Error!", "Connect failed");
        return;
    }

    String boundary = "----ESP32Bound";
    String partHead =
        "--" + boundary + "\r\n"
        "Content-Disposition: form-data; name=\"include_audio\"\r\n\r\n"
        "false\r\n"
        "--" + boundary + "\r\n"
        "Content-Disposition: form-data; name=\"audio\"; filename=\"rec.wav\"\r\n"
        "Content-Type: audio/wav\r\n\r\n";
    String partFoot = "\r\n--" + boundary + "--\r\n";

    int bodySize = partHead.length() + wavSize + partFoot.length();
    client.printf("POST %s HTTP/1.1\r\n", SERVER_PATH);
    client.printf("Host: %s:%d\r\n", SERVER_HOST, SERVER_PORT);
    client.println("Connection: close");
    client.println("Content-Type: multipart/form-data; boundary=" + boundary);
    client.printf("Content-Length: %d\r\n\r\n", bodySize);
    client.print(partHead);
    client.write(wavBuffer, wavSize);
    client.print(partFoot);

    String statusLine = client.readStringUntil('\n');
    int code = 0;
    if (statusLine.startsWith("HTTP/1.1 ") || statusLine.startsWith("HTTP/1.0 ")) {
        code = statusLine.substring(9, 12).toInt();
    }
    while (client.connected()) {
        String line = client.readStringUntil('\n');
        if (line == "\r" || line.length() == 0) break;
    }

    String resp = client.readString();
    client.stop();
    free(wavBuffer);
    wavBuffer = nullptr;
    wavSize = 0;

    if (code == 200) {
        handleResponse(resp);
    } else {
        Serial.printf("[HTTP] Error: %d\n", code);
        oledShow("Server Error!", ("Code: " + String(code)).c_str());
    }
}


// ─────────────────────────────────────────────
// WEBSOCKET LOW-LATENCY PCM STREAMING & WAKE WORD
// ─────────────────────────────────────────────
void sendToServerWebSocket(uint8_t* pcmBuf, int pcmSize) {
    if (WiFi.status() != WL_CONNECTED) {
        oledShow("WiFi Error!", "Reconnecting...");
        WiFi.reconnect(); delay(1000); return;
    }
    if (!pcmBuf || pcmSize <= 0) return;

    WiFiClient client;
    client.setTimeout(10);
    if (!client.connect(SERVER_HOST, SERVER_PORT)) {
        Serial.println("[WS] Server connect failed");
        return;
    }

    // Perform WebSocket HTTP Upgrade Handshake
    String secKey = "dGhlIHNhbXBsZSBub25jZQ==";
    client.printf("GET /ws/stream HTTP/1.1\r\n");
    client.printf("Host: %s:%d\r\n", SERVER_HOST, SERVER_PORT);
    client.printf("Upgrade: websocket\r\n");
    client.printf("Connection: Upgrade\r\n");
    client.printf("Sec-WebSocket-Key: %s\r\n", secKey.c_str());
    client.printf("Sec-WebSocket-Version: 13\r\n\r\n");

    // Read Handshake Header Response
    String line = client.readStringUntil('\n');
    if (!line.startsWith("HTTP/1.1 101")) {
        Serial.println("[WS] Handshake failed: " + line);
        client.stop();
        return;
    }

    // Stream raw PCM chunks in 512-byte WebSocket Binary Frames (Opcode 0x82)
    int chunkSize = 512;
    for (int offset = 0; offset < pcmSize; offset += chunkSize) {
        int bytesToSend = min(chunkSize, pcmSize - offset);

        // Frame header: 0x82 (FIN + Binary Frame), Length byte (with Mask bit set 0x80)
        uint8_t header[6];
        header[0] = 0x82;
        header[1] = 0x80 | bytesToSend; // 7-bit length + mask
        header[2] = 0x00; header[3] = 0x00; header[4] = 0x00; header[5] = 0x00; // Masking Key (all zeros)

        client.write(header, 6);
        client.write(pcmBuf + offset, bytesToSend);
        delay(2);
    }

    // Send control text frame: "END" (Opcode 0x81, Masked)
    uint8_t endFrame[9] = { 0x81, 0x83, 0x00, 0x00, 0x00, 0x00, 'E', 'N', 'D' };
    client.write(endFrame, 9);

    // Read WebSocket text response
    String wsResponse = client.readString();
    client.stop();

    if (wsResponse.length() > 0) {
        int jsonStart = wsResponse.indexOf('{');
        int jsonEnd = wsResponse.lastIndexOf('}');
        if (jsonStart >= 0 && jsonEnd > jsonStart) {
            String jsonBody = wsResponse.substring(jsonStart, jsonEnd + 1);
            handleResponse(jsonBody);
        }
    }
}


// ─────────────────────────────────────────────
// SETUP
// ─────────────────────────────────────────────
void setup() {
    Serial.begin(115200);

    // OLED
    Wire.begin(OLED_SDA, OLED_SCL);
    if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
        Serial.println("[OLED] Init failed!"); for(;;);
    }
    oledTitle("TamilVox", "Smart Home AI");
    delay(1000);

    // Relay pins — safe default OFF
    pinMode(RELAY_LIGHT, OUTPUT); relayOff(RELAY_LIGHT);
    pinMode(RELAY_FAN,   OUTPUT); relayOff(RELAY_FAN);
    pinMode(RELAY_AC,    OUTPUT); relayOff(RELAY_AC);

    // Button
    pinMode(BUTTON_PIN, INPUT_PULLUP);

    // I2S
    oledShow("Setting up", "microphone...");
    setupMic();
    oledShow("Setting up", "speaker...");
    setupAmp();

    // WiFi
    oledShow("Connecting WiFi", WIFI_SSID);
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    int tries = 0;
    while (WiFi.status() != WL_CONNECTED && tries < 30) {
        delay(500); Serial.print("."); tries++;
        oledShow("Connecting WiFi", WIFI_SSID, ("Attempt " + String(tries)).c_str());
    }

    if (WiFi.status() == WL_CONNECTED) {
        Serial.println("\n[WiFi] " + WiFi.localIP().toString());
        oledShow("WiFi Connected!", WiFi.localIP().toString().c_str());
        delay(1500);
    } else {
        oledShow("WiFi FAILED!", "Check credentials"); while(true) delay(1000);
    }

    // MQTT
    oledShow("Connecting", "MQTT broker...");
    wifiSecure.setInsecure();
    mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
    mqttClient.setCallback(mqttCallback);
    connectMqtt();

    // Ready
    oledStatus();
}


// ─────────────────────────────────────────────
// LOOP
// ─────────────────────────────────────────────
void loop() {
    // Keep MQTT alive
    if (!mqttClient.connected()) connectMqtt();
    mqttClient.loop();

    // BOOT button → speak (low latency WebSocket PCM streaming)
    if (digitalRead(BUTTON_PIN) == LOW) {
        delay(50); // debounce
        if (digitalRead(BUTTON_PIN) == LOW) {
            recordAudio();
            oledShow("Streaming...", "Low Latency WS");
            if (audioBuffer) {
                sendToServerWebSocket((uint8_t*)audioBuffer, TOTAL_SAMPLES * sizeof(int16_t));
            } else {
                sendToServer();
            }

            delay(2000);
            oledStatus(); // back to device status screen

            while (digitalRead(BUTTON_PIN) == LOW) delay(10);
        }
    }
}

