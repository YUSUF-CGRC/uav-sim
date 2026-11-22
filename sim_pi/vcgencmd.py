"""Sahte vcgencmd (Raspberry Pi'nin donanım bilgi komutu).

Kullanım:
    python sim_pi/vcgencmd.py get_throttled   -> throttled=0x0
    python sim_pi/vcgencmd.py measure_temp    -> temp=52.0'C

Değerleri sahte Cube'un yazdığı dosyalardan okur (sim_pi/throttled ve
sim_pi/thermal_zone0/temp). Sahte Cube çalışmıyorsa varsayılanları verir.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def read(path: Path, default: str) -> str:
    """Dosyayı okur; yoksa varsayılanı döndürür."""
    try:
        return path.read_text().strip()
    except OSError:
        return default


def main() -> int:
    """Komutu çalıştırır."""
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "get_throttled":
        print("throttled=" + read(HERE / "throttled", "0x0"))
        return 0
    if cmd == "measure_temp":
        milli = int(read(HERE / "thermal_zone0" / "temp", "50000"))
        print(f"temp={milli / 1000:.1f}'C")
        return 0
    print(f"Komut bulunamadı: {cmd}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
