"""Sahte Cube Orange+ (ArduPlane).

Gerçek Cube'un yaptığını taklit eder:
  * Belirli aralıklarla HEARTBEAT, SYS_STATUS, GPS_RAW_INT, RC_CHANNELS,
    SERVO_OUTPUT_RAW, GLOBAL_POSITION_INT ve ATTITUDE mesajları yollar.
  * PARAM_REQUEST_READ / PARAM_REQUEST_LIST isteklerine PARAM_VALUE ile cevap verir.
  * COMMAND_LONG isteklerine COMMAND_ACK ile cevap verir
    (DO_SET_SERVO, SET_MESSAGE_INTERVAL, REQUEST_MESSAGE).
  * İki "port"u vardır: Pi tarafı (TELEM2 gibi) ve Mission Planner tarafı (TELEM1 gibi).
    Bunlar gerçekte seri port, burada UDP. Mesajları portlar arasında yönlendirir.
  * Projede YASAK olan işlemleri (ARM, mod değiştirme, PARAM_SET, ...) yakalar,
    reddeder ve ekrana büyük bir uyarı basar.

Bu dosya senin yazacağın preflight kodunun bir parçası DEĞİL; sadece karşısındaki
"uçak" rolünü oynar.
"""

from __future__ import annotations

import logging
import os
import random
import time
from pathlib import Path
from typing import Any

# pymavlink'in MAVLink 2 kullanması için import'tan ÖNCE ayarlanmalı.
os.environ.setdefault("MAVLINK20", "1")

from pymavlink import mavutil  # noqa: E402
from pymavlink.dialects.v20 import ardupilotmega as mavlink2  # noqa: E402

from .scenario import pi_dir  # noqa: E402

log = logging.getLogger("fake_cube")


# SYS_STATUS içindeki sensör bitleri (MAV_SYS_STATUS_SENSOR)
SENSOR_BITS: dict[str, int] = {
    "gyro": mavlink2.MAV_SYS_STATUS_SENSOR_3D_GYRO,
    "accel": mavlink2.MAV_SYS_STATUS_SENSOR_3D_ACCEL,
    "mag": mavlink2.MAV_SYS_STATUS_SENSOR_3D_MAG,
    "baro": mavlink2.MAV_SYS_STATUS_SENSOR_ABSOLUTE_PRESSURE,
    "gps": mavlink2.MAV_SYS_STATUS_SENSOR_GPS,
    "rc": mavlink2.MAV_SYS_STATUS_SENSOR_RC_RECEIVER,
}

# Projede Pi'nin ASLA göndermemesi gereken komutlar ve mesajlar
FORBIDDEN_COMMANDS: dict[int, str] = {
    mavlink2.MAV_CMD_COMPONENT_ARM_DISARM: "ARM/DISARM",
    mavlink2.MAV_CMD_DO_SET_MODE: "uçuş modu değiştirme",
    mavlink2.MAV_CMD_MISSION_START: "görev başlatma",
    mavlink2.MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN: "otopilotu yeniden başlatma",
}
FORBIDDEN_MESSAGES: dict[str, str] = {
    "SET_MODE": "uçuş modu değiştirme",
    "PARAM_SET": "parametre yazma",
    "RC_CHANNELS_OVERRIDE": "RC override",
    "MISSION_COUNT": "görev yazma",
    "MISSION_ITEM": "görev yazma",
    "MISSION_ITEM_INT": "görev yazma",
    "MISSION_WRITE_PARTIAL_LIST": "görev yazma",
    "MISSION_CLEAR_ALL": "görev silme",
}

# SET_MESSAGE_INTERVAL'de kullanılan mesaj kimlikleri -> bizim iç adlarımız
PERIODIC_IDS: dict[int, str] = {
    mavlink2.MAVLINK_MSG_ID_HEARTBEAT: "HEARTBEAT",
    mavlink2.MAVLINK_MSG_ID_SYS_STATUS: "SYS_STATUS",
    mavlink2.MAVLINK_MSG_ID_GPS_RAW_INT: "GPS_RAW_INT",
    mavlink2.MAVLINK_MSG_ID_RC_CHANNELS: "RC_CHANNELS",
    mavlink2.MAVLINK_MSG_ID_SERVO_OUTPUT_RAW: "SERVO_OUTPUT_RAW",
    mavlink2.MAVLINK_MSG_ID_GLOBAL_POSITION_INT: "GLOBAL_POSITION_INT",
    mavlink2.MAVLINK_MSG_ID_ATTITUDE: "ATTITUDE",
}

# ArduPilot'ta bir kanalın parametreleri tanımlı değilse kullanılan değerler
DEFAULT_SERVO = {"function": 0, "min": 1100, "trim": 1500, "max": 1900}
SERVO_FUNCTION_NAMES = {0: "Disabled", 4: "Aileron", 19: "Elevator", 21: "Rudder",
                        70: "Throttle"}


class Link:
    """Cube'un bir portu (Pi tarafı veya Mission Planner tarafı)."""

    def __init__(self, name: str, address: str, sysid: int, compid: int,
                 packet_loss: float) -> None:
        self.name = name
        self.address = address
        self.packet_loss = packet_loss
        self.conn = mavutil.mavlink_connection(
            address, source_system=sysid, source_component=compid, dialect="ardupilotmega"
        )
        self.seen_peers: set[tuple[int, int]] = set()

    def send(self, msg: Any, mav: Any | None = None) -> None:
        """Mesajı paketleyip gönderir (packet_loss oranında paketi 'kaybeder')."""
        buf = msg.pack(mav or self.conn.mav)
        if self.packet_loss and random.random() < self.packet_loss:
            return
        self.send_raw(buf)

    def send_raw(self, buf: bytes) -> None:
        """Hazır paketlenmiş baytları gönderir (yönlendirme için)."""
        try:
            self.conn.write(buf)
        except OSError:
            # Karşı taraf (ör. Mission Planner) açık değilse UDP hata verebilir.
            pass

    def recv(self) -> Any | None:
        """Bekleyen bir mesaj varsa döndürür, yoksa None."""
        try:
            return self.conn.recv_match(blocking=False)
        except (OSError, ConnectionError):
            return None

    def close(self) -> None:
        """Bağlantıyı kapatır."""
        self.conn.close()


class FakeCube:
    """Senaryo dosyasına göre davranan sahte otopilot."""

    def __init__(self, scenario: dict[str, Any]) -> None:
        self.sc = scenario
        link = scenario["link"]
        hb = scenario["heartbeat"]
        self.sysid = int(hb["sysid"])
        self.compid = int(hb["compid"])
        self.pi = Link("Pi", link["pi_address"], self.sysid, self.compid,
                       float(link["packet_loss"]))
        self.gcs = (Link("MissionPlanner", link["gcs_address"], self.sysid, self.compid,
                         float(link["packet_loss"])) if link["gcs_enabled"] else None)
        # Pi tarafına giden sahte yer istasyonu heartbeat'i için ayrı kimlik (sysid 255)
        self.fake_gcs_mav = mavlink2.MAVLink(None, srcSystem=255, srcComponent=190)

        self.start = time.monotonic()
        self.armed = bool(hb["armed"])
        self.servo_params = self._build_servo_params(scenario["servo_params"])
        self.servo_cmd: dict[int, int] = {}       # DO_SET_SERVO ile verilen değerler
        self.violations = 0
        self.link_dead_logged = False

        self.default_rates = {
            "HEARTBEAT": float(hb["rate_hz"]) if hb["enabled"] else 0.0,
            "SYS_STATUS": float(scenario["sensors"]["rate_hz"]),
            "GPS_RAW_INT": float(scenario["gps"]["rate_hz"]),
            "RC_CHANNELS": float(scenario["rc"]["rate_hz"]),
            "SERVO_OUTPUT_RAW": float(scenario["servo"]["rate_hz"]),
            "GLOBAL_POSITION_INT": float(scenario["gps"]["rate_hz"]),
            "ATTITUDE": 1.0,
        }
        self.rates = dict(self.default_rates)
        self.next_send = {name: 0.0 for name in self.rates}

        folder = scenario["pi"]["folder"]
        self.pi_folder = Path(folder) if folder else pi_dir()
        self.next_pi_write = 0.0
        self.next_status = 0.0

    # ------------------------------------------------------------------ yardımcılar
    @staticmethod
    def _build_servo_params(raw: dict[str, Any]) -> dict[int, dict[str, int]]:
        params: dict[int, dict[str, int]] = {}
        for ch in range(1, 17):
            values = dict(DEFAULT_SERVO)
            values.update({k: int(v) for k, v in raw.get(str(ch), {}).items()})
            params[ch] = values
        return params

    def elapsed(self) -> float:
        """Simülasyon başından beri geçen süre (sn)."""
        return time.monotonic() - self.start

    def boot_ms(self) -> int:
        """Otopilotun açılıştan beri geçen süresi (ms)."""
        return int(self.elapsed() * 1000)

    def link_state(self) -> str:
        """'waiting' (henüz başlamadı), 'alive' veya 'dead' (kablo koptu)."""
        link = self.sc["link"]
        t = self.elapsed()
        if t < float(link["start_delay_s"]):
            return "waiting"
        stop = float(link["stop_after_s"])
        if stop > 0 and t > float(link["start_delay_s"]) + stop:
            return "dead"
        return "alive"

    def battery_v(self) -> float:
        """Zamanla düşen batarya voltajı."""
        b = self.sc["battery"]
        return max(0.0, float(b["voltage_v"]) - float(b["drain_v_per_min"]) * self.elapsed() / 60)

    def gps_state(self) -> tuple[int, int]:
        """(fix_type, uydu sayısı)."""
        g = self.sc["gps"]
        if self.elapsed() < float(g["fix_after_s"]):
            return 1, 3
        return int(g["fix_type"]), int(g["satellites"])

    def links(self) -> list[Link]:
        """Açık olan tüm portlar."""
        return [x for x in (self.pi, self.gcs) if x is not None]

    # ------------------------------------------------------------------ mesaj üretimi
    def make(self, name: str) -> Any | None:
        """İsmi verilen periyodik mesajı oluşturur."""
        m = self.pi.conn.mav
        if name == "HEARTBEAT":
            hb = self.sc["heartbeat"]
            base_mode = mavlink2.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED
            if self.armed:
                base_mode |= mavlink2.MAV_MODE_FLAG_SAFETY_ARMED
            status = mavlink2.MAV_STATE_ACTIVE if self.armed else mavlink2.MAV_STATE_STANDBY
            return m.heartbeat_encode(
                getattr(mavlink2, "MAV_TYPE_" + hb["vehicle_type"]),
                getattr(mavlink2, "MAV_AUTOPILOT_" + hb["autopilot"]),
                base_mode, 0, status)
        if name == "SYS_STATUS":
            s = self.sc["sensors"]
            present = 0
            for sensor in s["present"]:
                present |= SENSOR_BITS[sensor]
            unhealthy = 0
            for sensor in s["unhealthy"]:
                unhealthy |= SENSOR_BITS[sensor]
            health = present & ~unhealthy
            b = self.sc["battery"]
            return m.sys_status_encode(
                present, present, health, 250,
                int(self.battery_v() * 1000), int(float(b["current_a"]) * 100),
                int(b["remaining_pct"]), 0, 0, 0, 0, 0, 0)
        if name == "GPS_RAW_INT":
            g = self.sc["gps"]
            fix, sats = self.gps_state()
            return m.gps_raw_int_encode(
                self.boot_ms() * 1000, fix, int(g["lat"] * 1e7), int(g["lon"] * 1e7),
                int(g["alt_m"] * 1000), 120 if fix >= 3 else 9999, 180 if fix >= 3 else 9999,
                0, 0, sats)
        if name == "GLOBAL_POSITION_INT":
            g = self.sc["gps"]
            return m.global_position_int_encode(
                self.boot_ms(), int(g["lat"] * 1e7), int(g["lon"] * 1e7),
                int(g["alt_m"] * 1000), 0, 0, 0, 0, 0)
        if name == "ATTITUDE":
            return m.attitude_encode(self.boot_ms(), 0.0, 0.02, 1.57, 0.0, 0.0, 0.0)
        if name == "RC_CHANNELS":
            rc = self.sc["rc"]
            has_rc = "rc" in self.sc["sensors"]["present"]
            count = int(rc["chancount"]) if has_rc else 0
            chans = [65535] * 18                   # 65535 = kanal kullanılmıyor
            for i in range(count):
                chans[i] = 1000 if i == 2 else 1500  # 3. kanal gaz: en altta
            return m.rc_channels_encode(self.boot_ms(), count, *chans,
                                        int(rc["rssi"]) if has_rc else 0)
        if name == "SERVO_OUTPUT_RAW":
            return m.servo_output_raw_encode(self.boot_ms() * 1000, 0, *self.servo_outputs())
        return None

    def servo_outputs(self) -> list[int]:
        """16 kanalın o anki çıkış değeri (µs)."""
        noise = int(self.sc["servo"]["noise_us"])
        out = []
        for ch in range(1, 17):
            p = self.servo_params[ch]
            if p["function"] != 0:
                # Otopilot bu kanalı her döngüde kendisi yazar
                out.append(p["trim"] + random.randint(-noise, noise))
            elif ch in self.servo_cmd:
                out.append(self.servo_cmd[ch])
            else:
                out.append(0)   # boş kanal, henüz komut gelmedi: sinyal yok
        return out

    def send_periodic(self) -> None:
        """Zamanı gelen periyodik mesajları tüm portlara yollar."""
        now = time.monotonic()
        for name, rate in self.rates.items():
            if rate <= 0 or now < self.next_send[name]:
                continue
            self.next_send[name] = now + 1.0 / rate
            msg = self.make(name)
            for link in self.links():
                link.send(msg)
        if self.sc["gcs"]["fake_heartbeat"] and now >= self.next_send.get("_gcs_hb", 0.0):
            self.next_send["_gcs_hb"] = now + 1.0
            msg = self.fake_gcs_mav.heartbeat_encode(
                mavlink2.MAV_TYPE_GCS, mavlink2.MAV_AUTOPILOT_INVALID, 0, 0,
                mavlink2.MAV_STATE_ACTIVE)
            self.pi.send(msg, self.fake_gcs_mav)

    # ------------------------------------------------------------------ gelen mesajlar
    def violation(self, link: Link, what: str, msg: Any) -> None:
        """Yasaklı bir işlem yakalandığında çağrılır."""
        self.violations += 1
        log.error("!" * 60)
        log.error("YASAK İŞLEM (%s) %s tarafından gönderildi: %s", what, link.name, msg)
        log.error("Gerçek uçakta bu çok tehlikeli olurdu. Komut REDDEDİLDİ.")
        log.error("!" * 60)

    def ack(self, link: Link, command: int, result: int) -> None:
        """COMMAND_ACK gönderir."""
        link.send(link.conn.mav.command_ack_encode(command, result))

    def param_value(self, name: str) -> float | None:
        """SERVOx_FUNCTION / MIN / TRIM / MAX değerini döndürür."""
        if not name.startswith("SERVO") or "_" not in name:
            return None
        ch_text, field = name[5:].split("_", 1)
        if not ch_text.isdigit() or int(ch_text) not in self.servo_params:
            return None
        key = {"FUNCTION": "function", "MIN": "min", "TRIM": "trim", "MAX": "max"}.get(field)
        if key is None:
            return None
        return float(self.servo_params[int(ch_text)][key])

    def all_param_names(self) -> list[str]:
        """Sahte Cube'un bildiği tüm parametre adları."""
        return [f"SERVO{ch}_{f}" for ch in range(1, 17)
                for f in ("FUNCTION", "MIN", "TRIM", "MAX")]

    def send_param(self, link: Link, name: str, index: int) -> None:
        """Bir PARAM_VALUE mesajı yollar."""
        value = self.param_value(name)
        if value is None:
            return
        link.send(link.conn.mav.param_value_encode(
            name.encode(), value, mavlink2.MAV_PARAM_TYPE_INT16,
            len(self.all_param_names()), index))

    def for_me(self, msg: Any) -> bool:
        """Mesaj bu otopilota mı yönelik? (target_system 0 = herkese)"""
        target = getattr(msg, "target_system", 0)
        return target in (0, self.sysid)

    def handle(self, link: Link, msg: Any) -> None:
        """Bir porttan gelen mesajı işler."""
        mtype = msg.get_type()
        if mtype == "BAD_DATA":
            return
        peer = (msg.get_srcSystem(), msg.get_srcComponent())
        if peer not in link.seen_peers:
            link.seen_peers.add(peer)
            log.info("%s portunda yeni cihaz görüldü: sysid=%d compid=%d (%s)",
                     link.name, peer[0], peer[1], mtype)

        # Mesajı diğer porta yönlendir (Cube'un MAVLink routing'i gibi)
        if link is self.pi and self.gcs is not None:
            self.gcs.send_raw(msg.get_msgbuf())
        elif link is self.gcs and self.sc["gcs"]["forward_to_pi"]:
            self.pi.send_raw(msg.get_msgbuf())

        if not self.for_me(msg):
            return
        is_pi = link is self.pi

        if mtype in FORBIDDEN_MESSAGES:
            if is_pi:
                self.violation(link, FORBIDDEN_MESSAGES[mtype], msg)
            return
        if mtype == "PARAM_REQUEST_READ":
            name = msg.param_id.rstrip("\x00") if isinstance(msg.param_id, str) \
                else msg.param_id.decode().rstrip("\x00")
            names = self.all_param_names()
            if msg.param_index >= 0 and msg.param_index < len(names):
                name = names[msg.param_index]
            log.info("%s parametre okudu: %s = %s", link.name, name, self.param_value(name))
            if name in names:
                self.send_param(link, name, names.index(name))
        elif mtype == "PARAM_REQUEST_LIST":
            for i, name in enumerate(self.all_param_names()):
                self.send_param(link, name, i)
        elif mtype == "MISSION_REQUEST_LIST":
            link.send(link.conn.mav.mission_count_encode(peer[0], peer[1], 0))
        elif mtype in ("COMMAND_LONG", "COMMAND_INT"):
            self.handle_command(link, msg, is_pi)
        elif mtype == "STATUSTEXT":
            log.info("%s STATUSTEXT gönderdi (severity=%d): %s", link.name, msg.severity,
                     msg.text)

    def handle_command(self, link: Link, msg: Any, is_pi: bool) -> None:
        """COMMAND_LONG / COMMAND_INT işler ve COMMAND_ACK gönderir."""
        cmd = msg.command
        p1, p2 = msg.param1, msg.param2
        if cmd in FORBIDDEN_COMMANDS:
            if is_pi:
                self.violation(link, FORBIDDEN_COMMANDS[cmd], msg)
            self.ack(link, cmd, mavlink2.MAV_RESULT_DENIED)
            return
        if cmd == mavlink2.MAV_CMD_DO_SET_SERVO:
            self.do_set_servo(link, int(p1), int(p2))
        elif cmd == mavlink2.MAV_CMD_SET_MESSAGE_INTERVAL:
            self.set_interval(link, int(p1), float(p2))
        elif cmd == mavlink2.MAV_CMD_REQUEST_MESSAGE:
            name = PERIODIC_IDS.get(int(p1))
            if name is None:
                self.ack(link, cmd, mavlink2.MAV_RESULT_UNSUPPORTED)
                return
            self.ack(link, cmd, mavlink2.MAV_RESULT_ACCEPTED)
            link.send(self.make(name))
        else:
            log.info("%s bilinmeyen komut gönderdi: %d (UNSUPPORTED)", link.name, cmd)
            self.ack(link, cmd, mavlink2.MAV_RESULT_UNSUPPORTED)

    def do_set_servo(self, link: Link, ch: int, pwm: int) -> None:
        """MAV_CMD_DO_SET_SERVO: bir kanala PWM değeri verir."""
        cmd = mavlink2.MAV_CMD_DO_SET_SERVO
        if ch not in self.servo_params:
            log.warning("%s DO_SET_SERVO: geçersiz kanal %d", link.name, ch)
            self.ack(link, cmd, mavlink2.MAV_RESULT_DENIED)
            return
        p = self.servo_params[ch]
        result = int(self.sc["servo"]["ack_result"])
        if p["function"] != 0:
            fname = SERVO_FUNCTION_NAMES.get(p["function"], str(p["function"]))
            log.warning("%s DO_SET_SERVO kanal %d = %d: kanal otopilota ait (%s), "
                        "komut bir sonraki döngüde EZİLDİ", link.name, ch, pwm, fname)
        elif result == mavlink2.MAV_RESULT_ACCEPTED:
            self.servo_cmd[ch] = pwm + int(self.sc["servo"]["output_offset_us"])
            log.info("%s DO_SET_SERVO kanal %d = %d us", link.name, ch, pwm)
        self.ack(link, cmd, result)

    def set_interval(self, link: Link, msg_id: int, interval_us: float) -> None:
        """MAV_CMD_SET_MESSAGE_INTERVAL: bir mesajın gönderim sıklığını ayarlar."""
        cmd = mavlink2.MAV_CMD_SET_MESSAGE_INTERVAL
        name = PERIODIC_IDS.get(msg_id)
        if name is None:
            self.ack(link, cmd, mavlink2.MAV_RESULT_UNSUPPORTED)
            return
        if interval_us == 0:
            self.rates[name] = self.default_rates[name]      # 0 = varsayılana dön
            text = "varsayılan"
        elif interval_us < 0:
            self.rates[name] = 0.0                            # -1 = kapat
            text = "kapalı"
        else:
            self.rates[name] = 1e6 / interval_us
            text = f"{self.rates[name]:.1f} Hz"
        self.next_send[name] = 0.0
        log.info("%s %s mesaj hızını ayarladı: %s", link.name, name, text)
        self.ack(link, cmd, mavlink2.MAV_RESULT_ACCEPTED)

    # ------------------------------------------------------------------ sahte Pi dosyaları
    def write_pi_files(self) -> None:
        """Sahte CPU sıcaklığı ve throttling dosyalarını yazar."""
        now = time.monotonic()
        if now < self.next_pi_write:
            return
        self.next_pi_write = now + 1.0
        pi = self.sc["pi"]
        temp = float(pi["cpu_temp_c"]) + float(pi["temp_rise_c_per_min"]) * self.elapsed() / 60
        zone = self.pi_folder / "thermal_zone0"
        zone.mkdir(parents=True, exist_ok=True)
        # Gerçek Pi'de /sys/class/thermal/thermal_zone0/temp mili-derece içerir: 52000 = 52 C
        (zone / "temp").write_text(f"{int(temp * 1000)}\n")
        (self.pi_folder / "throttled").write_text(f"{pi['throttled']}\n")

    # ------------------------------------------------------------------ ana döngü
    def status_line(self) -> None:
        """Her 5 sn'de bir kısa durum özeti basar."""
        now = time.monotonic()
        if now < self.next_status:
            return
        self.next_status = now + 5.0
        fix, sats = self.gps_state()
        cmds = " ".join(f"ch{c}={v}" for c, v in sorted(self.servo_cmd.items())) or "-"
        log.info("[durum] bağlantı=%s arm=%s gps=fix%d/%d uydu batarya=%.1fV "
                 "servo komutları: %s yasak işlem: %d",
                 self.link_state(), self.armed, fix, sats, self.battery_v(), cmds,
                 self.violations)

    def step(self) -> None:
        """Ana döngünün bir adımı."""
        self.write_pi_files()
        self.status_line()
        state = self.link_state()
        if state == "dead" and not self.link_dead_logged:
            self.link_dead_logged = True
            log.warning("Senaryo: bağlantı KOPTU (stop_after_s doldu). Artık mesaj yok.")
        for link in self.links():
            for _ in range(50):
                msg = link.recv()
                if msg is None:
                    break
                if state == "alive":
                    self.handle(link, msg)
        if state == "alive":
            self.send_periodic()

    def run(self) -> None:
        """Ctrl+C gelene kadar çalışır."""
        try:
            while True:
                self.step()
                time.sleep(0.01)
        finally:
            for link in self.links():
                link.close()
            log.info("Sahte Cube kapandı. Toplam yasak işlem: %d", self.violations)
