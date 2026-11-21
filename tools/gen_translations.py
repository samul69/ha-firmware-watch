import json, os, sys

base = sys.argv[1]
P = ["synology", "omada", "tplink", "mikrotik", "dell", "lenovo", "samsung", "github", "web_regex", "json"]
FIELDS = {
    "synology": ["model", "region"],
    "omada": ["model", "region", "hardware_version"],
    "tplink": ["model", "hardware_version", "region"],
    "mikrotik": ["model", "channel", "major"],
    "dell": ["model"],
    "lenovo": ["machine_type", "os", "model"],
    "samsung": ["model", "csc"],
    "github": ["repository", "model", "include_prereleases"],
    "web_regex": ["url", "regex", "pick", "manufacturer", "model"],
    "json": ["url", "json_path", "manufacturer", "model"],
}
L = {
    "en": dict(
        provname={
            "synology": "Synology (DSM/SRM/BSM)",
            "omada": "TP-Link Omada (routers, switches, APs)",
            "tplink": "TP-Link (Archer, Deco, ...)",
            "mikrotik": "MikroTik RouterOS",
            "dell": "Dell BIOS (laptops, desktops)",
            "lenovo": "Lenovo BIOS (ThinkPad, ThinkCentre, ThinkStation)",
            "samsung": "Samsung Galaxy (phones, tablets)",
            "github": "GitHub releases",
            "web_regex": "Any web page + regular expression",
            "json": "Any JSON URL + path",
        },
        user_title="Firmware source",
        user_desc="Choose where the newest firmware version should be checked. The integration never logs in to your device.",
        label={
            "name": "Device name", "installed_version": "Installed firmware version",
            "scan_interval_hours": "Check interval", "model": "Model", "region": "Website region",
            "hardware_version": "Hardware version", "channel": "Release channel", "major": "Major version",
            "repository": "Repository (owner/name)", "include_prereleases": "Include pre-releases",
            "url": "URL", "regex": "Regular expression", "pick": "Which match to use",
            "manufacturer": "Manufacturer", "json_path": "Path in JSON",
            "machine_type": "Machine type", "os": "Operating system", "csc": "CSC (region code)",
        },
        desc={
            "synology": {"model": "Exactly as on synology.com, e.g. DS923+, DS920+, RT6600ax", "region": "Language code of synology.com, default en-global", "installed_version": "As shown in DSM, e.g. 7.2.2-72806 Update 3"},
            "omada": {"model": "Model slug from the support.omadanetworks.com URL, e.g. er605, sg2008p, eap653", "region": "Region in the URL: en (Europe), us, pl ...", "hardware_version": "Optional, e.g. 1.0 or 1.30 - only firmware for this hardware", "installed_version": "e.g. 1.2.11 Build 20260723"},
            "tplink": {"model": "Model slug from the tp-link.com URL, e.g. archer-ax55, deco-x50", "hardware_version": "e.g. 4 for V4 (sticker on the device)", "region": "Region in the URL, default en (global), e.g. uk, de, pl", "installed_version": "e.g. 1.2.0 Build 20260721 - compared by build date"},
            "mikrotik": {"model": "Optional, only for display, e.g. hAP ax3", "major": "RouterOS major version, default 7", "installed_version": "e.g. 7.19.4"},
            "dell": {"model": "As in Dell support, e.g. Latitude 5440, XPS 13 9340, OptiPlex 7010 - or the 4-digit system ID", "installed_version": "BIOS version from BIOS setup / msinfo32, e.g. 1.27.0"},
            "lenovo": {"machine_type": "First 4 characters of the MTM on the sticker, e.g. 21HD (from 21HDCTO1WW)", "os": "Catalog to use", "model": "Optional, only for display, e.g. ThinkPad T14 Gen 4", "installed_version": "e.g. N3QET52W (1.52) or 1.52"},
            "samsung": {"model": "e.g. SM-X710 (Settings - About - Model number)", "csc": "Region code, e.g. EUX (Europe tablets), XEO (Poland phones)", "installed_version": "Build number, e.g. X710XXU5CYJ3"},
            "github": {"repository": "e.g. openwrt/openwrt", "model": "Optional, only for display", "installed_version": "Tag without the leading v"},
            "web_regex": {"url": "Page with the download list / release notes", "regex": "Python regex; the first capture group is the version, e.g. Version (\\d+\\.\\d+\\.\\d+)", "pick": "highest = highest version found, first = first match on the page"},
            "json": {"url": "URL returning JSON", "json_path": "Dotted path, e.g. data.0.version or firmware.latest"},
        },
        step_title={"synology": "Synology device", "omada": "Omada device", "tplink": "TP-Link device", "mikrotik": "MikroTik device", "dell": "Dell computer", "lenovo": "Lenovo computer", "samsung": "Samsung Galaxy device", "github": "GitHub project", "web_regex": "Web page", "json": "JSON endpoint"},
        interval_desc="How often to check the vendor (hours), default 24",
        err="Could not read the newest version: {error}",
        abort="This device is already configured",
        opt_title="Device settings",
        opt_desc="After a manual upgrade change the installed version here (or use the action Set installed version).",
        pick={"highest": "Highest version", "first": "First match"},
        channel={"stable": "Stable", "long-term": "Long-term", "testing": "Testing", "development": "Development"},
        svc_name="Set installed version",
        svc_desc="Store the firmware version now running on the device (after a manual upgrade). Without a version the newest known version is used.",
        svc_ver="Version", svc_ver_desc="Installed version; empty = newest known version",
    ),
}


# ---- providers added later -------------------------------------------------
P += ["avm", "reolink", "unifi", "openwrt", "apple", "asus"]
FIELDS.update({
    "avm": ["model", "region"],
    "reolink": ["model", "hardware_version"],
    "unifi": ["platform", "product", "channel", "model"],
    "openwrt": ["model", "channel"],
    "apple": ["model"],
    "asus": ["model"],
})
EXTRA = {
    "en": dict(
        provname={"avm": "AVM FRITZ! (Box, Repeater, Powerline)", "reolink": "Reolink (cameras, doorbells, NVR)",
                  "unifi": "Ubiquiti UniFi (APs, switches, consoles, cameras)", "openwrt": "OpenWrt",
                  "apple": "Apple (iPad, iPhone, Apple silicon Mac)", "asus": "ASUS routers (older AC/AX models)"},
        label={"platform": "Platform", "product": "Product"},
        step_title={"avm": "FRITZ! device", "reolink": "Reolink device", "unifi": "UniFi device",
                    "openwrt": "OpenWrt router", "apple": "Apple device", "asus": "ASUS router"},
        desc={
            "avm": {"model": "Folder name from download.avm.de, e.g. fritzbox-7590, fritzbox-7530-ax, fritzrepeater-3000-ax", "region": "other = international firmware, deutschland = German", "installed_version": "e.g. 8.20 (FRITZ!OS 8.20)"},
            "reolink": {"model": "Product name as in the Reolink download center, e.g. RLC-810A, E1 Zoom, RLN8-410 - or product ID", "hardware_version": "Recommended - Hardware version from the app / web UI, e.g. IPC_523128M8MP", "installed_version": "e.g. v3.0.0.4867_2505072124"},
            "unifi": {"platform": "Platform code, e.g. U7PG2, US8P60 (devices), UDR, UCGMAX, UDMPRO (consoles), UNVR", "product": "unifi-firmware (APs, switches), unifi-dream (consoles), unifi-nvr, uvc (cameras)", "model": "Optional, only for display, e.g. U6 Lite", "installed_version": "e.g. 6.7.31"},
            "openwrt": {"model": "Optional, only for display", "channel": "stable = newest release, oldstable = previous series", "installed_version": "e.g. 24.10.2"},
            "apple": {"model": "Device name, e.g. iPad Air 5 (WiFi), iPhone 15 Pro, MacBook Air (M2, 2022) - or identifier like iPad13,16", "installed_version": "e.g. 18.6.2 (newest signed release is compared)"},
            "asus": {"model": "Model as in the router UI, e.g. RT-AC68U, RT-AX88U, GT-AX11000", "installed_version": "e.g. 3.0.0.4.386_48260"},
        },
        channel={"release": "Release", "release-candidate": "Release candidate", "beta": "Beta", "oldstable": "Old stable"},
        region={"other": "International", "deutschland": "Germany"},
    ),
}
for _lang, _ext in EXTRA.items():
    _t = L[_lang]
    for _k in ("provname", "label", "step_title", "desc", "channel"):
        _t[_k].update(_ext[_k])
    _t["region_sel"] = _ext["region"]
_ORDER = ["synology", "avm", "tplink", "omada", "unifi", "asus", "mikrotik", "openwrt", "reolink",
          "dell", "lenovo", "apple", "samsung", "github", "web_regex", "json"]
P = [p for p in _ORDER if p in P]
for _t in L.values():
    _t["provname"] = {p: _t["provname"][p] for p in P}


def build(t):
    steps = {"user": {"title": t["user_title"], "description": t["user_desc"], "data": {"provider": t["user_title"]}}}
    for p in P:
        keys = ["name", "installed_version"] + FIELDS[p] + ["scan_interval_hours"]
        dd = {"scan_interval_hours": t["interval_desc"], **t["desc"][p]}
        steps[p] = {
            "title": t["step_title"][p],
            "data": {k: t["label"][k] for k in keys},
            "data_description": {k: v for k, v in dd.items() if k in keys},
        }
    allf = sorted({f for v in FIELDS.values() for f in v})
    opt_keys = ["installed_version"] + allf + ["scan_interval_hours"]
    return {
        "config": {"step": steps, "error": {"cannot_fetch": t["err"]}, "abort": {"already_configured": t["abort"]}},
        "options": {
            "step": {"init": {"title": t["opt_title"], "description": t["opt_desc"],
                              "data": {k: t["label"][k] for k in opt_keys},
                              "data_description": {"scan_interval_hours": t["interval_desc"]}}},
            "error": {"cannot_fetch": t["err"]},
        },
        "selector": {
            "provider": {"options": t["provname"]},
            "pick": {"options": t["pick"]},
            "channel": {"options": t["channel"]},
            "os": {"options": {"win11": "Windows 11", "win10": "Windows 10"}},
            "region": {"options": t["region_sel"]},
        },
        "services": {"set_installed_version": {"name": t["svc_name"], "description": t["svc_desc"],
                                               "fields": {"version": {"name": t["svc_ver"], "description": t["svc_ver_desc"]}}}},
    }


os.makedirs(os.path.join(base, "translations"), exist_ok=True)
for lang in L:
    with open(os.path.join(base, "translations", f"{lang}.json"), "w", encoding="utf-8", newline=chr(10)) as f:
        json.dump(build(L[lang]), f, ensure_ascii=False, indent=2)
with open(os.path.join(base, "strings.json"), "w", encoding="utf-8", newline=chr(10)) as f:
    json.dump(build(L["en"]), f, ensure_ascii=False, indent=2)
print("ok")
