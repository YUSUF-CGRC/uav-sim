"""Senaryo (ayar) dosyasını okur.

Senaryo dosyası bir TOML dosyasıdır. Dosyada yazmadığın her değer aşağıdaki
DEFAULTS sözlüğünden gelir. Yani sadece değiştirmek istediğin şeyi yazman yeter.
Örnek: GPS'i bozmak için dosyaya sadece

    [gps]
    fix_type = 1
    satellites = 3

yazman yeterli.
"""

from __future__ import annotations

import copy
import os
import tomllib
from pathlib import Path
from typing import Any

# Ortam değişkeni: sahte kamera ve diğer parçalar senaryoyu buradan bulur.
SCENARIO_ENV = "UAV_SIM_SCENARIO"

DEFAULTS: dict[str, Any] = {
    "link": {
        # Pi tarafı: senin preflight kodun bu adresi dinler (udpin:0.0.0.0:14560)
        "pi_address": "udpout:127.0.0.1:14560",
        # Mission Planner tarafı: MP'de UDP, port 14550 seçerek bağlanırsın
        "gcs_address": "udpout:127.0.0.1:14550",
        "gcs_enabled": True,
        "start_delay_s": 0.0,     # Cube açıldıktan kaç sn sonra konuşmaya başlasın
        "stop_after_s": 0.0,      # 0 = hiç durma; >0 ise o kadar sn sonra kablo "kopar"
        "packet_loss": 0.0,       # 0.0 - 1.0 arası; giden paketlerin bu oranı kaybolur
    },
    "heartbeat": {
        "enabled": True,
        "rate_hz": 1.0,
        "vehicle_type": "FIXED_WING",     # MAV_TYPE_ adının devamı (ör. QUADROTOR)
        "autopilot": "ARDUPILOTMEGA",     # MAV_AUTOPILOT_ adının devamı
        "sysid": 1,
        "compid": 1,
        "armed": False,
    },
    "gcs": {
        # Mission Planner açık değilken bile Pi tarafına sysid 255 heartbeat'i gelsin mi?
        "fake_heartbeat": True,
        # Gerçek Mission Planner'dan gelen mesajlar Pi tarafına yönlendirilsin mi?
        # (Cube'un MAVLink yönlendirmesini taklit eder, gcs_link araştırması için)
        "forward_to_pi": True,
    },
    "sensors": {
        # Olası adlar: gyro, accel, mag, baro, gps, rc
        "present": ["gyro", "accel", "mag", "baro", "gps", "rc"],
        "unhealthy": [],            # present ama healthy DEĞİL olanlar
        "rate_hz": 1.0,
    },
    "battery": {
        "voltage_v": 15.8,
        "drain_v_per_min": 0.0,     # zamanla düşen batarya
        "current_a": 1.2,
        "remaining_pct": 90,
    },
    "gps": {
        "fix_type": 3,              # 0-1: fix yok, 2: 2D, 3: 3D, 4+: DGPS/RTK
        "satellites": 12,
        "fix_after_s": 0.0,         # bu süre dolana kadar fix_type=1, sats=3 gönderir
        "lat": 39.925533,           # Ankara
        "lon": 32.866287,
        "alt_m": 938.0,
        "rate_hz": 2.0,
    },
    "rc": {
        "chancount": 16,
        "rssi": 200,
        "rate_hz": 2.0,
    },
    "servo": {
        "rate_hz": 2.0,
        "noise_us": 2,              # otopilotun yönettiği kanallarda küçük oynama
        "output_offset_us": 0,      # komut verilen kanalda çıkış hedeften bu kadar sapar
        "ack_result": 0,            # DO_SET_SERVO cevabı (0 = ACCEPTED, 4 = FAILED ...)
    },
    # Kanal parametreleri. FUNCTION=0 ise kanal boştur, DO_SET_SERVO ile sürülebilir.
    # 1-4 kanallar sabit kanat için kontrol yüzeyleri (aileron, elevator, throttle, rudder).
    "servo_params": {
        "1": {"function": 4, "min": 1000, "trim": 1500, "max": 2000},
        "2": {"function": 19, "min": 1000, "trim": 1500, "max": 2000},
        "3": {"function": 70, "min": 1000, "trim": 1000, "max": 2000},
        "4": {"function": 21, "min": 1000, "trim": 1500, "max": 2000},
        "9": {"function": 0, "min": 1000, "trim": 1500, "max": 2000},
        "10": {"function": 0, "min": 1100, "trim": 1500, "max": 1900},
    },
    "camera": {
        "available": True,
        "width": 1920,
        "height": 1080,
        "fps": 30.0,
        "hang_on_open": False,      # Picamera2() sonsuza kadar takılsın mı (timeout testi)
        "hang_on_start": False,     # start() sonsuza kadar takılsın mı
        "fail_on_close": False,     # close() hata fırlatsın mı
    },
    "pi": {
        "cpu_temp_c": 52.0,
        "temp_rise_c_per_min": 0.0,
        "throttled": "0x0",         # vcgencmd get_throttled çıktısı (0x50005 = düşük voltaj)
        "folder": "sim_pi",         # sahte sıcaklık dosyasının yazılacağı klasör
    },
}


def _merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    """İç içe sözlükleri birleştirir; extra'daki değerler base'dekileri ezer."""
    result = copy.deepcopy(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def load_scenario(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Senaryo dosyasını okur ve varsayılanlarla birleştirir.

    path verilmezse UAV_SIM_SCENARIO ortam değişkenine bakılır. O da yoksa
    sadece varsayılanlar (her şey sağlıklı) kullanılır.
    """
    if path is None:
        path = os.environ.get(SCENARIO_ENV)
    if not path:
        return copy.deepcopy(DEFAULTS)
    with open(Path(path), "rb") as f:
        data = tomllib.load(f)
    return _merge(DEFAULTS, data)
