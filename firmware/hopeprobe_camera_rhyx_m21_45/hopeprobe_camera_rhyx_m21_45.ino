/*
  HOPEPROBE 3.0 - ESP32-CAM firmware for the RHYX M21-45 camera (GC2145)
  ======================================================================
  Standalone sketch. Independent of the DevKit V1 firmware and the dashboard.

  ENDPOINTS (CAMERA_IP is printed in the Serial Monitor, 115200 baud)
    http://CAMERA_IP:81/stream   MJPEG live stream  (paste into the dashboard sidebar)
    http://CAMERA_IP/status      JSON camera / Wi-Fi status
    http://CAMERA_IP/            tiny test page with the stream embedded

  BOARD ASSUMPTION (please check this first)
    The camera pin map below is the standard AI-Thinker ESP32-CAM map
    (Espressif's CAMERA_MODEL_AI_THINKER). The RHYX M21-45 is a GC2145 camera
    module with the 24-pin FPC used by AI-Thinker-style ESP32-CAM boards, so it
    is expected to plug straight in. If your board is a different model
    (ESP32-S3-CAM, TTGO, M5Stack, ...) the pin block must be replaced with the
    map printed on YOUR board's schematic. Wrong pins show up as
    "Camera probe failed" / error 0x105 or 0x20001 in the Serial Monitor.
    Pins are NOT guessed for other boards.

  WHY RGB565 + SOFTWARE JPEG
    The GC2145 has no hardware JPEG encoder, so frames are captured as RGB565
    and converted with Espressif's frame2jpg(). The cost is CPU time, so
    expect roughly 8-15 fps at QVGA (320x240).

  ARDUINO IDE SETUP
    1. Boards Manager -> "esp32" by Espressif Systems. Use 2.0.17 or a 3.x
       release. The GC2145 driver is only present in reasonably recent copies of
       the bundled esp32-camera driver: if init prints
       "Detected camera not supported" (0x106) update the core.
       (I could not compile or run this against a core here - see notes in chat.)
    2. Tools -> Board -> "AI Thinker ESP32-CAM".
    3. Tools -> PSRAM -> "Enabled" (needed for 320x240 RGB565 frame buffers).
       Without PSRAM the sketch falls back to 160x120.
    4. Partition scheme "Huge APP" or default are both fine.
    5. No extra libraries: esp_camera, WiFi and esp_http_server come with the core.
    6. Edit WIFI_SSID / WIFI_PASSWORD below (2.4 GHz network only).

  UPLOADING (AI-Thinker board has no USB chip)
    Use an FTDI/USB-serial adapter (3.3 V logic) or an ESP32-CAM-MB base board.
    Connect GPIO0 to GND, press RESET, upload, then REMOVE the GPIO0-GND link and
    press RESET again. Power with a solid 5 V (>= 500 mA). Weak power causes
    "Brownout detector was triggered" resets.

  LIMITS
    The stream server serves ONE viewer at a time (one browser tab / the
    dashboard). Close other tabs that show the stream.
*/

#include <Arduino.h>
#include <WiFi.h>
#include "esp_camera.h"
#include "img_converters.h"   // frame2jpg()
#include "esp_http_server.h"
#include "esp_timer.h"

// ============================ USER SETTINGS ================================
const char *WIFI_SSID     = "Airtel_sent_1988";
const char *WIFI_PASSWORD = "air64583";
const char *HOSTNAME      = "hopeprobe-cam";

#define STATUS_PORT        80
#define STREAM_PORT        81

#define FRAME_SIZE         FRAMESIZE_QVGA   // 320x240. Try FRAMESIZE_CIF / VGA later.
#define PIXEL_FORMAT       PIXFORMAT_RGB565 // If colours look wrong try PIXFORMAT_YUV422
#define JPEG_QUALITY       80               // frame2jpg: 1-100, HIGHER = better quality
#define TARGET_FPS         10               // upper limit; actual fps depends on the CPU
#define XCLK_HZ            20000000         // sensor clock; 2nd attempt uses the fallback
#define XCLK_FALLBACK_HZ   10000000
#define FLIP_VERTICAL      0                // 1 to flip the image upside down
#define FLIP_MIRROR        0                // 1 to mirror left/right
// ===========================================================================

#define FW_VERSION         "1.0"
#define EXPECTED_SENSOR_PID 0x2145          // GC2145

// ---- Camera pins: AI-Thinker ESP32-CAM (Espressif CAMERA_MODEL_AI_THINKER) ----
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22
#define FLASH_LED_GPIO_NUM 4                // on-board white LED, kept OFF

// ------------------------------- state --------------------------------------
static volatile bool     g_camOk = false;
static volatile int      g_clients = 0;
static volatile uint32_t g_frames = 0;
static volatile float    g_fps = 0;
static volatile int      g_w = 0, g_h = 0;
static volatile uint32_t g_lastJpegBytes = 0;
static uint16_t          g_sensorPid = 0;
static char              g_lastError[96] = "none";
static bool              g_serversStarted = false;
static uint32_t          g_camFailCount = 0;
static httpd_handle_t    g_statusHttpd = NULL;
static httpd_handle_t    g_streamHttpd = NULL;

static void setError(const char *msg) {
  strncpy(g_lastError, msg, sizeof(g_lastError) - 1);
  g_lastError[sizeof(g_lastError) - 1] = 0;
  Serial.printf("[ERR] %s\n", msg);
}

// ------------------------------- camera -------------------------------------
static bool initCamera(uint32_t xclkHz) {
  esp_camera_deinit();                       // harmless if not initialised
  g_camOk = false;

  camera_config_t c;
  memset(&c, 0, sizeof(c));
  c.ledc_channel = LEDC_CHANNEL_0;
  c.ledc_timer   = LEDC_TIMER_0;
  c.pin_d0 = Y2_GPIO_NUM;  c.pin_d1 = Y3_GPIO_NUM;
  c.pin_d2 = Y4_GPIO_NUM;  c.pin_d3 = Y5_GPIO_NUM;
  c.pin_d4 = Y6_GPIO_NUM;  c.pin_d5 = Y7_GPIO_NUM;
  c.pin_d6 = Y8_GPIO_NUM;  c.pin_d7 = Y9_GPIO_NUM;
  c.pin_xclk = XCLK_GPIO_NUM;
  c.pin_pclk = PCLK_GPIO_NUM;
  c.pin_vsync = VSYNC_GPIO_NUM;
  c.pin_href = HREF_GPIO_NUM;
  c.pin_sccb_sda = SIOD_GPIO_NUM;
  c.pin_sccb_scl = SIOC_GPIO_NUM;
  c.pin_pwdn = PWDN_GPIO_NUM;
  c.pin_reset = RESET_GPIO_NUM;
  c.xclk_freq_hz = xclkHz;
  c.pixel_format = PIXEL_FORMAT;             // GC2145: RGB565 or YUV422, never JPEG
  c.jpeg_quality = 12;                       // unused for non-JPEG formats

  if (psramFound()) {
    c.frame_size   = FRAME_SIZE;
    c.fb_count     = 2;                      // double buffer
    c.fb_location  = CAMERA_FB_IN_PSRAM;
    c.grab_mode    = CAMERA_GRAB_LATEST;     // always newest frame, no stale backlog
  } else {
    Serial.println("[WARN] No PSRAM found - falling back to QQVGA 160x120, 1 buffer in DRAM");
    c.frame_size   = FRAMESIZE_QQVGA;
    c.fb_count     = 1;
    c.fb_location  = CAMERA_FB_IN_DRAM;
    c.grab_mode    = CAMERA_GRAB_WHEN_EMPTY;
  }

  esp_err_t err = esp_camera_init(&c);
  if (err != ESP_OK) {
    char m[96];
    snprintf(m, sizeof(m), "Camera init failed: 0x%x (%s) @ XCLK %lu Hz",
             err, esp_err_to_name(err), (unsigned long)xclkHz);
    setError(m);
    if (err == ESP_ERR_NOT_SUPPORTED)
      Serial.println("      -> core's esp32-camera driver does not know this sensor: update the ESP32 core.");
    else
      Serial.println("      -> check FPC cable seating, 5 V supply, and that the pin map matches your board.");
    esp_camera_deinit();
    return false;
  }

  sensor_t *s = esp_camera_sensor_get();
  if (!s) {
    setError("Camera init OK but sensor handle is NULL");
    esp_camera_deinit();
    return false;
  }
  g_sensorPid = s->id.PID;
  Serial.printf("[CAM] Sensor PID 0x%04X, XCLK %lu Hz\n", g_sensorPid, (unsigned long)xclkHz);
  if (g_sensorPid != EXPECTED_SENSOR_PID)
    Serial.printf("[WARN] Expected GC2145 (0x%04X) but detected 0x%04X - streaming anyway\n",
                  EXPECTED_SENSOR_PID, g_sensorPid);

  // Only generic orientation controls (no sensor-specific tuning). Guarded in
  // case a sensor driver leaves a function pointer empty.
  if (s->set_vflip)  s->set_vflip(s, FLIP_VERTICAL);
  if (s->set_hmirror) s->set_hmirror(s, FLIP_MIRROR);

  g_camOk = true;
  g_camFailCount = 0;
  strcpy(g_lastError, "none");
  Serial.println("[CAM] Camera ready");
  return true;
}

// ------------------------------- HTTP ---------------------------------------
static const char *STREAM_CT       = "multipart/x-mixed-replace;boundary=hpframe";
static const char *STREAM_BOUNDARY = "\r\n--hpframe\r\n";
static const char *STREAM_PART     = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

static esp_err_t stream_handler(httpd_req_t *req) {
  if (!g_camOk) {
    httpd_resp_set_status(req, "503 Service Unavailable");
    return httpd_resp_send(req, "Camera not ready", HTTPD_RESP_USE_STRLEN);
  }
  httpd_resp_set_type(req, STREAM_CT);
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  httpd_resp_set_hdr(req, "Cache-Control", "no-store");

  g_clients++;
  Serial.println("[STREAM] client connected");
  const int64_t frameUs = 1000000LL / TARGET_FPS;
  esp_err_t res = ESP_OK;
  int capFails = 0, convFails = 0;
  int64_t lastDone = 0;

  while (res == ESP_OK) {
    if (!g_camOk || WiFi.status() != WL_CONNECTED) break;
    int64_t t0 = esp_timer_get_time();

    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb) {
      if (++capFails >= 10) {
        setError("Frame capture failed 10x - camera will be re-initialised");
        g_camOk = false;                     // loop() re-initialises it
        break;
      }
      delay(50);
      continue;
    }
    capFails = 0;
    g_w = fb->width;
    g_h = fb->height;

    uint8_t *jpg = NULL;
    size_t jpgLen = 0;
    bool ok = frame2jpg(fb, JPEG_QUALITY, &jpg, &jpgLen);
    esp_camera_fb_return(fb);                // always hand the frame buffer back

    if (!ok || !jpg || jpgLen == 0) {
      if (jpg) free(jpg);
      setError("JPEG conversion failed");
      if (++convFails >= 5) break;
      delay(20);
      continue;
    }
    convFails = 0;

    char hdr[64];
    size_t hl = snprintf(hdr, sizeof(hdr), STREAM_PART, (unsigned)jpgLen);
    res = httpd_resp_send_chunk(req, STREAM_BOUNDARY, strlen(STREAM_BOUNDARY));
    if (res == ESP_OK) res = httpd_resp_send_chunk(req, hdr, hl);
    if (res == ESP_OK) res = httpd_resp_send_chunk(req, (const char *)jpg, jpgLen);
    free(jpg);                               // always free the JPEG buffer

    if (res == ESP_OK) {
      g_frames++;
      g_lastJpegBytes = jpgLen;
      int64_t now = esp_timer_get_time();
      if (lastDone) {
        float inst = 1e6f / (float)(now - lastDone);
        g_fps = (g_fps == 0) ? inst : (g_fps * 0.8f + inst * 0.2f);
      }
      lastDone = now;
      int64_t spare = frameUs - (now - t0);
      delay(spare > 1000 ? (uint32_t)(spare / 1000) : 1);   // pace + yield
    }
  }

  g_clients--;
  if (g_clients == 0) g_fps = 0;
  Serial.printf("[STREAM] client disconnected (%s)\n", esp_err_to_name(res));
  if (res == ESP_OK) httpd_resp_send_chunk(req, NULL, 0);   // clean end of response
  return res;
}

static esp_err_t status_handler(httpd_req_t *req) {
  char ip[16] = "0.0.0.0";
  if (WiFi.status() == WL_CONNECTED) WiFi.localIP().toString().toCharArray(ip, sizeof(ip));
  char err[96];
  strncpy(err, g_lastError, sizeof(err));
  for (char *p = err; *p; ++p) if (*p == '"' || *p == '\\') *p = '\'';   // keep JSON valid

  char buf[640];
  snprintf(buf, sizeof(buf),
    "{\"firmware\":\"%s\",\"camera\":\"%s\",\"sensor_pid\":\"0x%04X\",\"sensor_is_gc2145\":%s,"
    "\"pixel_format\":\"%s\",\"width\":%d,\"height\":%d,\"fps\":%.1f,\"frames_sent\":%lu,"
    "\"last_jpeg_bytes\":%lu,\"stream_clients\":%d,\"stream_url\":\"http://%s:%d/stream\","
    "\"wifi\":\"%s\",\"ssid\":\"%s\",\"ip\":\"%s\",\"rssi\":%d,\"uptime_s\":%lu,"
    "\"psram\":%s,\"free_heap\":%lu,\"free_psram\":%lu,\"last_error\":\"%s\"}",
    FW_VERSION, g_camOk ? "ok" : "error", g_sensorPid,
    (g_sensorPid == EXPECTED_SENSOR_PID) ? "true" : "false",
    (PIXEL_FORMAT == PIXFORMAT_RGB565) ? "RGB565->JPEG" : "YUV422->JPEG",
    (int)g_w, (int)g_h, (double)g_fps, (unsigned long)g_frames,
    (unsigned long)g_lastJpegBytes, (int)g_clients, ip, STREAM_PORT,
    WiFi.status() == WL_CONNECTED ? "connected" : "disconnected", WIFI_SSID, ip,
    WiFi.status() == WL_CONNECTED ? WiFi.RSSI() : 0,
    (unsigned long)(millis() / 1000), psramFound() ? "true" : "false",
    (unsigned long)ESP.getFreeHeap(), (unsigned long)ESP.getFreePsram(), err);

  httpd_resp_set_type(req, "application/json");
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  httpd_resp_set_hdr(req, "Cache-Control", "no-store");
  return httpd_resp_send(req, buf, HTTPD_RESP_USE_STRLEN);
}

static esp_err_t index_handler(httpd_req_t *req) {
  char html[420];
  char ip[16] = "0.0.0.0";
  WiFi.localIP().toString().toCharArray(ip, sizeof(ip));
  snprintf(html, sizeof(html),
    "<!doctype html><title>HOPEPROBE CAM</title>"
    "<body style='background:#0b0c0a;color:#c9d1b8;font-family:monospace'>"
    "<h3>HOPEPROBE 3.0 - CAMERA</h3><img src='http://%s:%d/stream' style='max-width:100%%'>"
    "<p><a style='color:#8a9a5b' href='/status'>/status</a></p></body>", ip, STREAM_PORT);
  httpd_resp_set_type(req, "text/html");
  return httpd_resp_send(req, html, HTTPD_RESP_USE_STRLEN);
}

static void startServers() {
  httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
  cfg.server_port = STATUS_PORT;
  cfg.max_open_sockets = 4;
  cfg.lru_purge_enable = true;

  httpd_uri_t idx;    memset(&idx, 0, sizeof(idx));
  idx.uri = "/";       idx.method = HTTP_GET; idx.handler = index_handler;
  httpd_uri_t st;     memset(&st, 0, sizeof(st));
  st.uri = "/status";  st.method = HTTP_GET;  st.handler = status_handler;

  if (httpd_start(&g_statusHttpd, &cfg) == ESP_OK) {
    httpd_register_uri_handler(g_statusHttpd, &idx);
    httpd_register_uri_handler(g_statusHttpd, &st);
  } else {
    setError("Could not start status server");
  }

  cfg.server_port = STREAM_PORT;
  cfg.ctrl_port  += 1;                       // second server needs its own control port
  cfg.stack_size  = 8192;                    // JPEG conversion needs stack
  cfg.max_open_sockets = 3;

  httpd_uri_t strm;   memset(&strm, 0, sizeof(strm));
  strm.uri = "/stream"; strm.method = HTTP_GET; strm.handler = stream_handler;
  if (httpd_start(&g_streamHttpd, &cfg) == ESP_OK) {
    httpd_register_uri_handler(g_streamHttpd, &strm);
  } else {
    setError("Could not start stream server");
  }
  g_serversStarted = (g_statusHttpd != NULL && g_streamHttpd != NULL);
  if (g_serversStarted) {
    Serial.printf("[HTTP] Stream: http://%s:%d/stream\n", WiFi.localIP().toString().c_str(), STREAM_PORT);
    Serial.printf("[HTTP] Status: http://%s/status\n", WiFi.localIP().toString().c_str());
  }
}

// ------------------------------- Wi-Fi --------------------------------------
static void onWiFiEvent(WiFiEvent_t event, WiFiEventInfo_t info) {
  if (event == ARDUINO_EVENT_WIFI_STA_DISCONNECTED) {
    Serial.printf("[WIFI] Disconnected (reason %d)\n", info.wifi_sta_disconnected.reason);
  } else if (event == ARDUINO_EVENT_WIFI_STA_GOT_IP) {
    Serial.printf("[WIFI] Connected, IP %s\n", WiFi.localIP().toString().c_str());
  }
}

static void beginWiFi() {
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

static bool connectWiFi(uint32_t timeoutMs) {
  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.setHostname(HOSTNAME);
  WiFi.setSleep(false);                      // lower latency for streaming
  WiFi.setAutoReconnect(true);
  WiFi.onEvent(onWiFiEvent);
  Serial.printf("[WIFI] Connecting to \"%s\" ...\n", WIFI_SSID);
  beginWiFi();
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < timeoutMs) delay(250);
  return WiFi.status() == WL_CONNECTED;
}

// ------------------------------- Arduino ------------------------------------
void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\n=== HOPEPROBE 3.0 camera firmware (RHYX M21-45 / GC2145) ===");
  Serial.printf("Firmware %s, PSRAM: %s\n", FW_VERSION, psramFound() ? "yes" : "NO");

  pinMode(FLASH_LED_GPIO_NUM, OUTPUT);
  digitalWrite(FLASH_LED_GPIO_NUM, LOW);

  if (!initCamera(XCLK_HZ)) {
    Serial.println("[CAM] Retrying with lower sensor clock");
    initCamera(XCLK_FALLBACK_HZ);
  }

  if (connectWiFi(20000)) {
    startServers();
  } else {
    setError("Wi-Fi not connected at start - will keep retrying");
  }
}

void loop() {
  static uint32_t lastWifiTry = 0, lastCamTry = 0, lastReport = 0;
  uint32_t now = millis();

  // ---- Wi-Fi supervision
  if (WiFi.status() != WL_CONNECTED) {
    if (now - lastWifiTry > 10000) {
      lastWifiTry = now;
      Serial.println("[WIFI] Not connected - retrying");
      WiFi.disconnect();
      beginWiFi();
    }
  } else if (!g_serversStarted) {
    startServers();                          // first successful connection
  }

  // ---- camera supervision (only when nobody is streaming)
  if (!g_camOk && g_clients == 0 && now - lastCamTry > 15000) {
    lastCamTry = now;
    g_camFailCount++;
    Serial.printf("[CAM] Re-initialising (attempt %lu)\n", (unsigned long)g_camFailCount);
    bool ok = initCamera((g_camFailCount % 2) ? XCLK_FALLBACK_HZ : XCLK_HZ);
    if (!ok && g_camFailCount >= 20) {
      Serial.println("[CAM] Giving up retries - restarting ESP32");
      delay(200);
      ESP.restart();
    }
  }

  // ---- periodic serial report
  if (now - lastReport > 10000) {
    lastReport = now;
    Serial.printf("[INFO] cam=%s wifi=%s ip=%s rssi=%d clients=%d fps=%.1f heap=%lu psram=%lu\n",
      g_camOk ? "ok" : "ERROR",
      WiFi.status() == WL_CONNECTED ? "up" : "DOWN",
      WiFi.localIP().toString().c_str(),
      WiFi.status() == WL_CONNECTED ? WiFi.RSSI() : 0,
      (int)g_clients, (double)g_fps,
      (unsigned long)ESP.getFreeHeap(), (unsigned long)ESP.getFreePsram());
  }
  delay(50);
}
