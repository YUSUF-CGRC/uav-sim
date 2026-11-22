"""Komut satırı: python -m uav_sim --scenario scenarios/normal.toml"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from .scenario import SCENARIO_ENV, load_scenario


def main() -> int:
    """Sahte Cube'u başlatır."""
    parser = argparse.ArgumentParser(description="Sahte Cube Orange+ (ArduPlane) simülatörü")
    parser.add_argument("--scenario", "-s", help="senaryo TOML dosyası (ör. scenarios/normal.toml)")
    parser.add_argument("--verbose", "-v", action="store_true", help="daha fazla log")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    path = args.scenario or os.environ.get(SCENARIO_ENV)
    scenario = load_scenario(path)

    from .fake_cube import FakeCube   # pymavlink'i ancak burada yükle

    cube = FakeCube(scenario)
    link = scenario["link"]
    print("=" * 70)
    print(" Sahte Cube Orange+ (ArduPlane) çalışıyor")
    print(f" Senaryo           : {path or '(varsayılan: her şey sağlıklı)'}")
    print(f" Pi tarafı (TELEM2): {link['pi_address']}")
    print("   -> preflight kodunda bağlantı adresi: udpin:0.0.0.0:"
          + link["pi_address"].rsplit(":", 1)[1])
    if link["gcs_enabled"]:
        print(f" Mission Planner   : {link['gcs_address']}  (MP'de UDP + port "
              + link["gcs_address"].rsplit(":", 1)[1] + ")")
    print(" Durdurmak için Ctrl+C")
    print("=" * 70)
    try:
        cube.run()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
