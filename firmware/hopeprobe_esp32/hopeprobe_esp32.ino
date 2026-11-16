/*
  HOPEPROBE 3.0 - ESP32 DevKit V1 example firmware
  Implements the dashboard serial protocol (115200 baud, ASCII lines).

  Libraries (Arduino IDE -> Library Manager):
    - Adafruit MLX90614 Library   (also installs Adafruit BusIO)

  Board: "ESP32 Dev Module"

  PC -> ESP32            ESP32 -> PC
    CMD,F|B|L|R|S          HELLO,HOPEPROBE,<fw>
    PING                   TEMP,<obj>,<amb>
    HELLO?                 DIST,<cm>            (only if ENABLE_ULTRASONIC 1)
                           STATUS,MLX,<0|1>
                           STATUS,US,<0|1>
                           ACK,<cmd>   PONG   ERR,<text>

  Safety: motors stop if nothing is received from the PC for 3 seconds.

  Wiring (L298N driver, ENA/ENB jumpers left ON = full speed):
    IN1=26  IN2=27  (left motor)     IN3=14  IN4=12 (right motor)
    MLX90614: SDA=21, SCL=22, 3.3V, GND
    HC-SR04 (optional): TRIG=5, ECHO=18  -> ECHO is 5 V! use a voltage
    divider (e.g. 1k + 2k) before the ESP32 pin.
  If a motor spins the wrong way, swap its two wires on the L298N.
*/

#include <Wire.h>
#include <Adafruit_MLX90614.h>

#define FW_VERSION "1.0"
#define ENABLE_ULTRASONIC 0        // set to 1 once the HC-SR04 is fitted

const int IN1 = 26, IN2 = 27, IN3 = 14, IN4 = 12;
const int TRIG_PIN = 5, ECHO_PIN = 18;

const unsigned long PC_TIMEOUT_MS = 3000;
const unsigned long TEMP_EVERY_MS = 500;
const unsigned long DIST_EVERY_MS = 300;
const unsigned long STATUS_EVERY_MS = 5000;

Adafruit_MLX90614 mlx;
bool mlxOk = false;
bool moving = false;
String rxLine;
unsigned long lastPcMsg = 0, tTemp = 0, tDist = 0, tStatus = 0;

void drive(int a, int b, int c, int d) {
  digitalWrite(IN1, a); digitalWrite(IN2, b);
  digitalWrite(IN3, c); digitalWrite(IN4, d);
}

void stopMotors() { drive(LOW, LOW, LOW, LOW); moving = false; }

void sendStatus() {
  Serial.print("STATUS,MLX,"); Serial.println(mlxOk ? 1 : 0);
  Serial.print("STATUS,US,");  Serial.println(ENABLE_ULTRASONIC ? 1 : 0);
}

void announce() {
  Serial.print("HELLO,HOPEPROBE,"); Serial.println(FW_VERSION);
  sendStatus();
}

void handleCommand(char c) {
  switch (c) {
    case 'F': drive(HIGH, LOW, HIGH, LOW); moving = true; break;
    case 'B': drive(LOW, HIGH, LOW, HIGH); moving = true; break;
    case 'L': drive(LOW, HIGH, HIGH, LOW); moving = true; break;   // spin left
    case 'R': drive(HIGH, LOW, LOW, HIGH); moving = true; break;   // spin right
    case 'S': stopMotors(); break;
    default:
      Serial.println("ERR,UNKNOWN_CMD");
      return;
  }
  Serial.print("ACK,"); Serial.println(c);
}

void handleLine(String line) {
  line.trim();
  if (line.length() == 0) return;
  lastPcMsg = millis();
  if (line == "PING") Serial.println("PONG");
  else if (line == "HELLO?") announce();
  else if (line.startsWith("CMD,") && line.length() >= 5) handleCommand(line.charAt(4));
  else Serial.println("ERR,BAD_MESSAGE");
}

#if ENABLE_ULTRASONIC
float readDistanceCm() {
  digitalWrite(TRIG_PIN, LOW);  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH); delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);
  unsigned long us = pulseIn(ECHO_PIN, HIGH, 30000);   // ~5 m timeout
  if (us == 0) return -1;                               // no echo
  return us * 0.0343f / 2.0f;
}
#endif

void setup() {
  Serial.begin(115200);
  pinMode(IN1, OUTPUT); pinMode(IN2, OUTPUT);
  pinMode(IN3, OUTPUT); pinMode(IN4, OUTPUT);
  stopMotors();
#if ENABLE_ULTRASONIC
  pinMode(TRIG_PIN, OUTPUT); pinMode(ECHO_PIN, INPUT);
#endif
  Wire.begin(21, 22);
  mlxOk = mlx.begin();
  lastPcMsg = millis();
  delay(300);
  announce();
}

void loop() {
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\n') { handleLine(rxLine); rxLine = ""; }
    else if (ch != '\r' && rxLine.length() < 64) rxLine += ch;
  }

  unsigned long now = millis();

  if (moving && now - lastPcMsg > PC_TIMEOUT_MS) {       // link-loss failsafe
    stopMotors();
    Serial.println("ERR,WATCHDOG_STOP");
  }

  if (mlxOk && now - tTemp >= TEMP_EVERY_MS) {
    tTemp = now;
    float o = mlx.readObjectTempC(), a = mlx.readAmbientTempC();
    if (!isnan(o) && !isnan(a)) {                        // only real readings
      Serial.print("TEMP,"); Serial.print(o, 1); Serial.print(",");
      Serial.println(a, 1);
    } else {
      Serial.println("ERR,MLX_READ");
    }
  }

#if ENABLE_ULTRASONIC
  if (now - tDist >= DIST_EVERY_MS) {
    tDist = now;
    float d = readDistanceCm();
    if (d > 0) { Serial.print("DIST,"); Serial.println(d, 0); }
  }
#endif

  if (now - tStatus >= STATUS_EVERY_MS) {
    tStatus = now;
    sendStatus();
  }
}
