import asyncio
import importlib.util
import sys
import types

import os
PKG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "custom_components", "firmware_watch")
pkg = types.ModuleType("fw")
pkg.__path__ = [PKG]
sys.modules["fw"] = pkg
for name in ("cab", "providers"):
    spec = importlib.util.spec_from_file_location(f"fw.{name}", f"{PKG}/{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"fw.{name}"] = mod
    spec.loader.exec_module(mod)
P = sys.modules["fw.providers"].PROVIDERS

CASES = [
    ("synology", {"model": "DS923+", "installed_version": "7.2.2-72806 Update 3"}),
    ("omada", {"model": "er605", "region": "en", "installed_version": "2.4.0 Build 20260101"}),
    ("omada", {"model": "er605", "region": "en", "installed_version": "2.4.10 Build 20260916 Rel. 12345"}),
    ("tplink", {"model": "archer-ax55", "hardware_version": "4", "region": "en", "installed_version": "1.1.0 Build 20250101"}),
    ("tplink", {"model": "archer-c6", "hardware_version": "3", "region": "en", "installed_version": "1.0.0 Build 20200101"}),
    ("mikrotik", {"channel": "stable", "installed_version": "7.19.4"}),
    ("dell", {"model": "Latitude 5440", "installed_version": "1.27.0"}),
    ("dell", {"model": "OptiPlex 7010", "installed_version": "1.0.0"}),
    ("lenovo", {"machine_type": "21HD", "os": "win11", "installed_version": "N3QET50W (1.50)"}),
    ("lenovo", {"machine_type": "82JW", "os": "win11", "installed_version": "HHCN32WW"}),
    ("samsung", {"model": "SM-X710", "csc": "EUX", "installed_version": "X710XXU5CYA1"}),
    ("github", {"repository": "esphome/esphome", "installed_version": "2025.1.0"}),
    ("web_regex", {"url": "https://upgrade.mikrotik.com/routeros/NEWESTa7.stable", "regex": r"(\d+\.\d+(?:\.\d+)?)", "pick": "first", "installed_version": "7.25.1"}),
    ("json", {"url": "https://api.github.com/repos/home-assistant/core/releases/latest", "json_path": "tag_name", "installed_version": "2026.10.1"}),
    ("avm", {"model": "fritzbox-7590", "region": "other", "installed_version": "FRITZ!OS 8.20"}),
    ("avm", {"model": "FRITZ!Repeater 3000 AX", "region": "other", "installed_version": "8.00"}),
    ("reolink", {"model": "E1 Zoom", "installed_version": "v3.0.0.0_20010100"}),
    ("reolink", {"model": "RLC-810A", "installed_version": "v3.0.0.0_20010100"}),
    ("unifi", {"platform": "U7PG2", "product": "unifi-firmware", "installed_version": "6.6.77"}),
    ("unifi", {"platform": "UDR", "product": "unifi-dream", "installed_version": "4.0.0"}),
    ("openwrt", {"channel": "stable", "installed_version": "OpenWrt 24.10.2 r28739"}),
    ("apple", {"model": "iPad Air 5 (WiFi)", "installed_version": "18.6.2"}),
    ("apple", {"model": "iPhone15,2", "installed_version": "18.0"}),
    ("asus", {"model": "RT-AC68U", "installed_version": "3.0.0.4.386_49000"}),
    ("asus", {"model": "RT-AX58U", "installed_version": "3.0.0.4.388_1"}),
]


async def main():
    import aiohttp
    async with aiohttp.ClientSession() as s:
        for key, conf in CASES:
            p = P[key]
            try:
                r = await p.async_latest(s, conf)
                newer = p.is_newer(r.version, conf["installed_version"])
                print(f"OK  {key:9} {conf.get('model') or conf.get('machine_type') or conf.get('repository') or ''!s:15} latest={r.version!r} newer_than({conf['installed_version']!r})={newer} pub={r.published} url={r.release_url}")
            except Exception as e:  # noqa
                print(f"ERR {key:9} {e!r}"[:300])

    # version comparison sanity checks
    syn, om, tpl, sam, len_ = P["synology"], P["omada"], P["tplink"], P["samsung"], P["lenovo"]
    assert syn.is_newer("7.4.1-90080 Update 2", "7.4-90075")
    assert not syn.is_newer("7.4.1-90080", "7.4.1-90080 Update 2")
    assert syn.is_newer("7.4.1-90080 Update 2", "7.4.1-90080 Update 1")
    assert not om.is_newer("1.3.1 Build 20260915", "1.3.1 Build 20260915 Rel. 65170")
    assert tpl.is_newer("251030 (2025-10-30)", "1.2.3 Build 20250101")
    assert not tpl.is_newer("251030 (2025-10-30)", "1.2.3 Build 20251030 rel.5")
    assert sam.is_newer("X710XXU5CYJ3", "UP1A.231005.007.X710XXU5CYA1")
    assert sam.is_newer("X710XXU6DZA1", "X710XXU5CYJ3")
    assert not len_.is_newer("1.52", "N3QET52W (1.52)")
    assert not tpl.is_newer("1.11.2 Build 26102114", "1.11.2 Build 26102114")
    assert tpl.is_newer("1.11.2 Build 26102114", "1.11.0 Build 25060110")
    assert tpl.is_newer("1.2.0 Build 20260721", "251030")
    assert len_.is_newer("HHCN37WW", "HHCN32WW")
    assert not len_.is_newer("PQCN32WW", "PQCN32WW")
    assert len_.is_newer("1.53", "N3QET52W")
    assert not len_.is_newer("1.52", "N3QET52W")
    uni, avm, asus, ow = P["unifi"], P["avm"], P["asus"], P["openwrt"]
    assert not uni.is_newer("6.0.17+7bcad58", "6.0.17")
    assert uni.is_newer("6.8.2+15592", "6.7.31")
    assert not avm.is_newer("8.51", "164.08.51")
    assert avm.is_newer("8.51", "FRITZ!OS 8.20")
    assert not asus.is_newer("3.0.0.4.386_51665", "3.0.0.4.386_51665")
    assert asus.is_newer("3.0.0.4.388_24198", "3.0.0.4.386_51665")
    assert not ow.is_newer("25.12.6", "OpenWrt 25.12.6 r30000")
    print("comparisons OK")


asyncio.run(main())
