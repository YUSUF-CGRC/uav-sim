"""Sahte picamera2 kütüphanesi (Windows'ta kamerasız deneme için).

Gerçek picamera2'nin en çok kullanılan kısmını taklit eder:
    Picamera2(), global_camera_info(), create_*_configuration(), configure(),
    start(), capture_array(), capture_metadata(), stop(), close()

Nasıl kullanılır? Kendi kodunda HİÇBİR ŞEY değiştirme, normal şekilde
    from picamera2 import Picamera2
yaz. Simülasyonda çalıştırırken PYTHONPATH'e bu klasörün üstünü (sim_libs) eklersin,
Python gerçek kütüphane yerine bunu bulur. Gerçek Pi'de PYTHONPATH'i eklemezsin,
gerçek kütüphane çalışır.

Davranış, UAV_SIM_SCENARIO ortam değişkenindeki senaryo dosyasının [camera]
bölümünden okunur (kamera yok, takılma, düşük FPS, yanlış çözünürlük...).
"""

from __future__ import annotations

import logging
import os
import time
import tomllib
from typing import Any

import numpy as np

__all__ = ["Picamera2"]

log = logging.getLogger("picamera2(sahte)")

_DEFAULTS: dict[str, Any] = {
    "available": True,
    "width": 1920,
    "height": 1080,
    "fps": 30.0,
    "hang_on_open": False,
    "hang_on_start": False,
    "fail_on_close": False,
}


def _settings() -> dict[str, Any]:
    """Senaryodaki [camera] ayarlarını okur (her kamera açılışında yeniden)."""
    settings = dict(_DEFAULTS)
    path = os.environ.get("UAV_SIM_SCENARIO")
    if path:
        with open(path, "rb") as f:
            settings.update(tomllib.load(f).get("camera", {}))
    return settings


def _hang(where: str) -> None:
    """Gerçek bir donanım takılmasını taklit eder: hiç geri dönmez."""
    log.warning("Senaryo: kamera %s sırasında TAKILDI (sonsuza kadar bekliyor)", where)
    while True:
        time.sleep(1.0)


class Picamera2:
    """Sahte Raspberry Pi kamerası."""

    _in_use: set[int] = set()   # aynı anda açık kameralar (kapatmayı unutmayı yakalar)

    def __init__(self, camera_num: int = 0, tuning: Any = None) -> None:
        self._cfg = _settings()
        self.camera_num = camera_num
        self._open = False
        self._started = False
        self._config: dict[str, Any] | None = None
        self._next_frame = 0.0
        self._frame_count = 0
        if self._cfg["hang_on_open"]:
            _hang("açılış (Picamera2())")
        if not self._cfg["available"] or camera_num != 0:
            raise IndexError("list index out of range (kamera bulunamadı)")
        if camera_num in Picamera2._in_use:
            raise RuntimeError("Failed to acquire camera: Device or resource busy "
                               "(önceki kamera close() ile kapatılmamış!)")
        Picamera2._in_use.add(camera_num)
        self._open = True
        w, h = int(self._cfg["width"]), int(self._cfg["height"])
        self.camera_properties: dict[str, Any] = {
            "Model": "imx708 (sahte)",
            "PixelArraySize": (w, h),
        }
        log.info("kamera açıldı (en fazla %dx%d @ %.1f fps)", w, h, float(self._cfg["fps"]))

    # ------------------------------------------------------------ bilgi
    @staticmethod
    def global_camera_info() -> list[dict[str, Any]]:
        """Bağlı kameraların listesi (kamera yoksa boş liste)."""
        if not _settings()["available"]:
            return []
        return [{"Model": "imx708 (sahte)", "Location": 2, "Num": 0}]

    # ------------------------------------------------------------ yapılandırma
    def _make_config(self, main: dict[str, Any] | None,
                     controls: dict[str, Any] | None) -> dict[str, Any]:
        main = dict(main or {})
        main.setdefault("size", (640, 480))
        main.setdefault("format", "RGB888")
        return {"main": main, "controls": dict(controls or {})}

    def create_preview_configuration(self, main: dict[str, Any] | None = None,
                                     controls: dict[str, Any] | None = None,
                                     **kwargs: Any) -> dict[str, Any]:
        """Önizleme yapılandırması oluşturur."""
        return self._make_config(main, controls)

    def create_still_configuration(self, main: dict[str, Any] | None = None,
                                   controls: dict[str, Any] | None = None,
                                   **kwargs: Any) -> dict[str, Any]:
        """Fotoğraf yapılandırması oluşturur."""
        return self._make_config(main, controls)

    def create_video_configuration(self, main: dict[str, Any] | None = None,
                                   controls: dict[str, Any] | None = None,
                                   **kwargs: Any) -> dict[str, Any]:
        """Video yapılandırması oluşturur."""
        return self._make_config(main, controls)

    def configure(self, camera_config: dict[str, Any] | None = None) -> None:
        """Yapılandırmayı uygular. Kamera en fazla sensör boyutunu verebilir."""
        self._check_open()
        config = camera_config or self._make_config(None, None)
        req_w, req_h = config["main"]["size"]
        max_w, max_h = self.camera_properties["PixelArraySize"]
        size = (min(int(req_w), max_w), min(int(req_h), max_h))
        if size != (req_w, req_h):
            log.warning("istenen %dx%d desteklenmiyor, %dx%d kullanılacak",
                        req_w, req_h, size[0], size[1])
        config["main"]["size"] = size
        self._config = config
        self._blank = np.zeros((size[1], size[0], 3), dtype=np.uint8)

    # ------------------------------------------------------------ çalışma
    def start(self, config: dict[str, Any] | None = None, show_preview: bool = False) -> None:
        """Kamerayı başlatır."""
        self._check_open()
        if config is not None or self._config is None:
            self.configure(config)
        if self._cfg["hang_on_start"]:
            _hang("start()")
        self._started = True
        self._next_frame = time.monotonic() + 1.0 / float(self._cfg["fps"])
        log.info("kamera başlatıldı")

    def _wait_frame(self) -> None:
        if not self._started:
            raise RuntimeError("Camera must be started before capturing (önce start())")
        fps = float(self._cfg["fps"])
        now = time.monotonic()
        if now < self._next_frame:
            time.sleep(self._next_frame - now)
        self._next_frame = max(now, self._next_frame) + 1.0 / fps
        self._frame_count += 1

    def capture_array(self, name: str = "main") -> np.ndarray:
        """Bir kare alır (yükseklik x genişlik x 3 numpy dizisi)."""
        self._wait_frame()
        frame = self._blank.copy()
        frame[:, :, 1] = self._frame_count % 256     # her karede biraz değişsin
        return frame

    def capture_metadata(self) -> dict[str, Any]:
        """Bir karenin bilgilerini döndürür."""
        self._wait_frame()
        return {"SensorTimestamp": time.monotonic_ns(),
                "FrameDuration": int(1e6 / float(self._cfg["fps"]))}

    def stop(self) -> None:
        """Kamerayı durdurur (açık kalır)."""
        if self._started:
            log.info("kamera durduruldu")
        self._started = False

    def close(self) -> None:
        """Kamerayı kapatır; başka bir kullanıcı artık açabilir."""
        if self._cfg["fail_on_close"]:
            raise RuntimeError("Senaryo: kamera kapatılırken hata (fail_on_close)")
        self.stop()
        if self._open:
            Picamera2._in_use.discard(self.camera_num)
            self._open = False
            log.info("kamera kapatıldı")

    def _check_open(self) -> None:
        if not self._open:
            raise RuntimeError("Camera is not open (kamera kapalı)")

    def __enter__(self) -> "Picamera2":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
