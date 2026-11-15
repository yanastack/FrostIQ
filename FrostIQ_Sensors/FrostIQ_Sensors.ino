#include <Wire.h>
#include <Arduino_Modulino.h>
#include <Arduino_RouterBridge.h>
#include <math.h>

ModulinoThermo thermo;
ModulinoDistance doorDistance;
bool distanceStarted;
String latestPacket;
unsigned long sampledAt;
unsigned long sampleId = 0;

String readSensors() {
  return latestPacket;
}

void sampleSensors() {
  const float temperature = thermo.getTemperature();
  float distanceCm = NAN;
  if (distanceStarted && doorDistance.available()) {
    distanceCm = doorDistance.get() / 10.0f;
  }

  const bool temperatureValid = isfinite(temperature);
  const bool distanceValid = isfinite(distanceCm) && distanceCm > 0;
  const char* distanceStatus = distanceStarted ? "read_error" : "unavailable";
  if (distanceValid) {
    distanceStatus = "ok";
  }

  latestPacket = "{\"sample_id\":" + String(++sampleId) + ",\"readings\":{\"temperature_c\":";
  latestPacket += temperatureValid ? String(temperature, 2) : String("null");
  latestPacket += ",\"distance_cm\":";
  latestPacket += distanceValid ? String(distanceCm, 1) : String("null");
  latestPacket += ",\"motion_detected\":null},\"sensor_status\":{\"temperature_c\":\"";
  latestPacket += temperatureValid ? "ok" : "read_error";
  latestPacket += "\",\"distance_cm\":\"";
  latestPacket += distanceStatus;
  latestPacket += "\",\"motion_detected\":\"unavailable\"}}";
  Serial.println(latestPacket);
}

void setup() {
  Bridge.begin();
  Serial.begin(115200);
  Modulino.begin(Wire1);
  thermo.begin();
  distanceStarted = doorDistance.begin();
  sampleSensors();
  sampledAt = millis();
  Bridge.provide_safe("frostiq_read_sensors", readSensors);
}

void loop() {
  if (millis() - sampledAt >= 1000) {
    sampledAt = millis();
    sampleSensors();
  }
}
