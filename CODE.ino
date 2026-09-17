// ESP32 + HC-SR04 + Green/Red LEDs + 3-pin Buzzer
// Emits JSON on serial for the Python bridge

#define TRIG_PIN   5
#define ECHO_PIN   34
#define LED_GREEN  26
#define LED_RED    27
#define BUZZER_PIN 25

#define ALERT_DISTANCE_CM 20.0
#define READ_INTERVAL_MS  500

// ─────────────────────────────────────────────────────────
//  BUZZER CONFIG
//  Most 3-pin modules are active-HIGH (beep when pin = HIGH).
//  If your buzzer beeps CONSTANTLY at boot and goes silent
//  during alert, set this to true.
// ─────────────────────────────────────────────────────────
#define BUZZER_ACTIVE_LOW false

void buzzerOn()  { digitalWrite(BUZZER_PIN, BUZZER_ACTIVE_LOW ? LOW  : HIGH); }
void buzzerOff() { digitalWrite(BUZZER_PIN, BUZZER_ACTIVE_LOW ? HIGH : LOW);  }

void setup() {
  Serial.begin(115200);

  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  pinMode(LED_GREEN, OUTPUT);
  pinMode(LED_RED, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);

  digitalWrite(TRIG_PIN, LOW);
  digitalWrite(LED_GREEN, LOW);
  digitalWrite(LED_RED, LOW);
  buzzerOff();

  delay(500);  // let things settle

  // ── Boot self-test: 2 short beeps + LED flash ──
  for (int i = 0; i < 2; i++) {
    digitalWrite(LED_GREEN, HIGH);
    digitalWrite(LED_RED, HIGH);
    buzzerOn();
    delay(150);
    digitalWrite(LED_GREEN, LOW);
    digitalWrite(LED_RED, LOW);
    buzzerOff();
    delay(150);
  }

  Serial.println("{\"status\":\"ready\"}");
}

float readDistanceCM() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  long duration = pulseIn(ECHO_PIN, HIGH, 30000);  // 30 ms timeout
  return duration * 0.0343 / 2.0;
}

void loop() {
  float distance = readDistanceCM();
  bool alert = (distance > 0.5 && distance < ALERT_DISTANCE_CM);

  // ── LEDs ──
  digitalWrite(LED_GREEN, alert ? LOW  : HIGH);
  digitalWrite(LED_RED,   alert ? HIGH : LOW);

  // ── Buzzer: 3 fast beeps + pause when alert ──
  if (alert) {
    for (int i = 0; i < 3; i++) {
      buzzerOn();  delay(80);
      buzzerOff(); delay(80);
    }
    delay(260);  // pause between bursts (total ~740 ms)
  } else {
    buzzerOff();
    delay(READ_INTERVAL_MS);  // 500 ms
  }

  // ── JSON line for the bridge ──
  Serial.print("{\"distance\":");
  Serial.print(distance, 2);
  Serial.print(",\"alert\":");
  Serial.print(alert ? "true" : "false");
  Serial.print(",\"buzzer\":");
  Serial.print(alert ? "true" : "false");
  Serial.print(",\"led_green\":");
  Serial.print(alert ? "false" : "true");
  Serial.print(",\"led_red\":");
  Serial.print(alert ? "true" : "false");
  Serial.println("}");
}