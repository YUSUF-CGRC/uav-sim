"""uav-sim komut satırı.

    uav-sim                         -> sahte Cube, "normal" senaryo
    uav-sim gps_yok                 -> sahte Cube, gps_yok senaryosu
    uav-sim list                    -> hazır senaryoları listeler
    uav-sim run gps_yok -- python -m preflight --check-only
                                    -> sahte Cube'u arka planda açar, senin komutunu
                                       sahte kamera ve Pi ayarlarıyla çalıştırır, sonra kapatır
    uav-sim env gps_yok             -> iki ayrı terminal kullanmak istersen gereken ayarlar
    uav-sim vcgencmd get_throttled  -> sahte vcgencmd
    uav-sim paths                   -> config dosyana yazacağın sahte Pi yolları

`uav-sim` komutu bulunamazsa her yerde `python -m uav_sim` yazabilirsin.
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from .scenario import (PI_DIR_ENV, SCENARIO_ENV, SIM_LIBS_DIR, list_scenarios, load_scenario,
                       pi_dir, resolve_scenario)

SUBCOMMANDS = {"cube", "list", "run", "env", "vcgencmd", "paths"}
PI_PORT_HINT = "udpin:0.0.0.0:14560"


def sim_env(scenario: Path | None) -> dict[str, str]:
    """Senin kodunun simülasyonda çalışması için gereken ortam değişkenleri."""
    env: dict[str, str] = {}
    if scenario is not None:
        env[SCENARIO_ENV] = str(scenario)
    old = os.environ.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(SIM_LIBS_DIR) + (os.pathsep + old if old else "")
    env[PI_DIR_ENV] = str(pi_dir())
    return env


# ---------------------------------------------------------------------- alt komutlar
def cmd_cube(scenario_name: str | None, verbose: bool) -> int:
    """Sahte Cube'u ön planda çalıştırır (Ctrl+C ile durur)."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    path = resolve_scenario(scenario_name or os.environ.get(SCENARIO_ENV) or "normal")
    scenario = load_scenario(path)

    from .fake_cube import FakeCube   # pymavlink'i ancak burada yükle

    cube = FakeCube(scenario)
    link = scenario["link"]
    print("=" * 70)
    print(" Sahte Cube Orange+ (ArduPlane) çalışıyor")
    print(f" Senaryo           : {path.stem if path else '-'}  ({path})")
    print(f" Pi tarafı (TELEM2): {link['pi_address']}")
    print("   -> preflight kodunda bağlantı adresi: udpin:0.0.0.0:"
          + link["pi_address"].rsplit(":", 1)[1])
    if link["gcs_enabled"]:
        print(f" Mission Planner   : {link['gcs_address']}  (MP'de UDP + port "
              + link["gcs_address"].rsplit(":", 1)[1] + ")")
    print(f" Sahte Pi dosyaları: {cube.pi_folder}")
    print(" Durdurmak için Ctrl+C")
    print("=" * 70, flush=True)
    try:
        cube.run()
    except KeyboardInterrupt:
        pass
    return 0


def cmd_list() -> int:
    """Hazır senaryoları listeler."""
    print("Hazır senaryolar (kullanım: python -m uav_sim <ad>):\n")
    for name, desc in list_scenarios():
        print(f"  {name:22s} {desc}")
    print("\nKendi senaryon için bir .toml dosyası yazıp yolunu verebilirsin: "
          "python -m uav_sim benim.toml")
    return 0


def _pump(stream: object, prefix: str, counter: list[int], show: bool) -> None:
    """Sahte Cube'un çıktısını başına etiket koyarak ekrana aktarır, yasak işlemleri sayar."""
    for line in stream:  # type: ignore[attr-defined]
        if "YASAK İŞLEM" in line:
            counter[0] += 1
        if show:
            sys.stdout.write(prefix + line)
            sys.stdout.flush()


def cmd_run(scenario_name: str, command: list[str], quiet: bool) -> int:
    """Sahte Cube'u arka planda açar, komutu çalıştırır, sonra Cube'u kapatır."""
    if not command:
        print("Çalıştırılacak komut yok. Örnek:\n"
              "  python -m uav_sim run gps_yok -- python -m preflight --check-only")
        return 2
    path = resolve_scenario(scenario_name)
    env = dict(os.environ)
    env.update(sim_env(path))
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    cube = subprocess.Popen(
        [sys.executable, "-m", "uav_sim", "cube", str(path)],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace")
    violations = [0]
    threading.Thread(target=_pump, args=(cube.stdout, "[cube] ", violations, not quiet),
                     daemon=True).start()
    time.sleep(1.0)     # Cube'un açılması için kısa bir süre
    print(f"[uav-sim] senaryo={path.stem}  komut: {' '.join(command)}", flush=True)
    code = 0
    try:
        child = subprocess.Popen(command, env=env)
        while True:
            try:
                code = child.wait()
                break
            except KeyboardInterrupt:
                # Ctrl+C senin programına da gider; onun temiz kapanmasını bekleriz.
                continue
    except FileNotFoundError:
        print(f"[uav-sim] komut bulunamadı: {command[0]}")
        code = 127
    finally:
        cube.terminate()
        try:
            cube.wait(timeout=3)
        except subprocess.TimeoutExpired:
            cube.kill()
    print(f"[uav-sim] programın çıkış kodu: {code}", flush=True)
    if violations[0]:
        print(f"[uav-sim] DİKKAT: programın {violations[0]} YASAK İŞLEM gönderdi!", flush=True)
    else:
        print("[uav-sim] yasak işlem yok.", flush=True)
    return code


def cmd_env(scenario_name: str) -> int:
    """İki terminalle çalışmak için ortam değişkenlerini yazdırır."""
    path = resolve_scenario(scenario_name)
    env = sim_env(path)
    print("Komut İstemi (cmd) için, kendi kodunu çalıştıracağın pencereye yapıştır:\n")
    for key, value in env.items():
        print(f'  set "{key}={value}"')
    print("\nPowerShell için:\n")
    for key, value in env.items():
        print(f'  $env:{key} = "{value}"')
    print("\nSahte Cube'u başka bir pencerede başlat:  python -m uav_sim", path.stem)
    print(f"Kodunda bağlantı adresi: {PI_PORT_HINT}")
    return 0


def cmd_vcgencmd(args: list[str]) -> int:
    """Sahte vcgencmd: get_throttled / measure_temp."""
    folder = pi_dir()
    what = args[0] if args else ""

    def read(name: str, default: str) -> str:
        try:
            return (folder / name).read_text().strip()
        except OSError:
            return default

    if what == "get_throttled":
        print("throttled=" + read("throttled", "0x0"))
        return 0
    if what == "measure_temp":
        print(f"temp={int(read('thermal_zone0/temp', '50000')) / 1000:.1f}'C")
        return 0
    print(f"Komut bulunamadı: {what}", file=sys.stderr)
    return 1


def cmd_paths() -> int:
    """Config dosyasına yazılacak sahte Pi yollarını gösterir."""
    folder = pi_dir()
    print("Simülasyon config dosyana yazabileceğin değerler:\n")
    print(f'  port          = "{PI_PORT_HINT}"')
    print(f'  thermal_path  = "{(folder / "thermal_zone0" / "temp").as_posix()}"')
    print('  throttled_cmd = ["python", "-m", "uav_sim", "vcgencmd", "get_throttled"]')
    print("\n(Gerçek Pi'de: /dev/ttyAMA0, /sys/class/thermal/thermal_zone0/temp,"
          ' ["vcgencmd", "get_throttled"])')
    return 0


# ---------------------------------------------------------------------- giriş noktası
def main(argv: list[str] | None = None) -> int:
    """Komut satırını ayrıştırır ve ilgili alt komutu çalıştırır."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if not argv or argv[0] not in SUBCOMMANDS:
        argv = ["cube"] + argv          # "uav-sim gps_yok" = "uav-sim cube gps_yok"
    sub, rest = argv[0], argv[1:]
    try:
        if sub == "cube":
            parser = argparse.ArgumentParser(prog="uav-sim")
            parser.add_argument("scenario", nargs="?", help="senaryo adı ya da .toml yolu")
            parser.add_argument("-v", "--verbose", action="store_true")
            args = parser.parse_args(rest)
            return cmd_cube(args.scenario, args.verbose)
        if sub == "list":
            return cmd_list()
        if sub == "run":
            if "--" in rest:
                i = rest.index("--")
                head, command = rest[:i], rest[i + 1:]
            else:
                head, command = rest[:1], rest[1:]
            quiet = "-q" in head
            names = [x for x in head if x != "-q"]
            return cmd_run(names[0] if names else "normal", command, quiet)
        if sub == "env":
            return cmd_env(rest[0] if rest else "normal")
        if sub == "vcgencmd":
            return cmd_vcgencmd(rest)
        return cmd_paths()
    except FileNotFoundError as exc:
        print(exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
