# Firmware Watch (Home Assistant)

One place to track firmware updates for any device. The integration **never logs in to your hardware**:
you enter the installed version in the configuration, and the integration checks the newest version
(every 24 h by default) on the vendor's website or public API.

Each device is a separate config entry with an `update.<name>` entity (device class `firmware`).
When the vendor publishes a newer version, the entity turns `on` and shows up under
**Settings → Updates** with a link to the release notes. The "Skip" button works as usual.
There is no "Install" button, because the integration does not install anything.

## Sources

| Provider | What to enter | Source |
|---|---|---|
| **Network & NAS** | | |
| Synology | model `DS923+` | public synology.com API (including "Update N") |
| AVM FRITZ! | `fritzbox-7590`, `fritzrepeater-3000-ax` | download.avm.de |
| TP-Link (Archer, Deco) | slug `archer-ax55`, HW `4`, region `en` (default) / `uk` / `de` | tp-link.com (compared by build date) |
| TP-Link Omada | slug `er605`, region `en`, optional HW version | support.omadanetworks.com |
| Ubiquiti UniFi | platform `U7PG2` / `UDR`, product `unifi-firmware` / `unifi-dream` | fw-update.ubnt.com |
| ASUS (older routers) | `RT-AC68U`, `RT-AX88U` | ASUS LiveUpdate list |
| MikroTik | channel `stable` | upgrade.mikrotik.com |
| OpenWrt | channel `stable` | downloads.openwrt.org |
| **Cameras** | | |
| Reolink | `RLC-810A`, `E1 Zoom` + HW version | Reolink Download Center API |
| **Computers & tablets** | | |
| Dell BIOS | `Latitude 5440` or system ID `0C00` | Dell Command Update catalog (downloads.dell.com) |
| Lenovo BIOS | machine type `21HD` | Lenovo System Update catalog (ThinkPad / ThinkCentre / ThinkStation) |
| Apple | `iPad Air 5 (WiFi)`, `iPhone15,2` | ipsw.me (newest signed release) |
| Samsung Galaxy | `SM-X710`, CSC `EUX` | Samsung FOTA server ⚠️ not verified |
| **Generic** | | |
| GitHub | `owner/repo` | GitHub releases API |
| Web page + regex | URL + regex with a capture group `( )` | any web page |
| JSON | URL + path `data.0.version` | any JSON API |

When you add a device, the integration fetches the newest version right away. If the configuration
is wrong, you get an error explaining why.

### Notes
- **Dell**: some names are reused across generations (e.g. "OptiPlex 7010" from 2012 and 2023).
  In that case enter the 4-character system ID (PowerShell: `(Get-CimInstance Win32_ComputerSystem).SystemSKUNumber`).
- **Lenovo**: only the Think\* lines, because IdeaPad/Yoga have no public catalog. Lenovo Android
  tablets don't have one either. If you find a page that lists versions, use the "web page + regex" provider.
- **Samsung**: the public `version.xml` endpoint returned HTTP 403 during development. It may work from
  your network; adding the device will tell you.
- **TP-Link**: if a hardware revision isn't sold in a region, the site redirects to a different revision.
  The integration detects this and reports an error instead of returning the wrong version.
- **ASUS**: the public LiveUpdate list mostly covers AC and early AX models (RT-AX88U, GT-AX11000).
  Newer models (RT-AX58U, ZenWiFi, BE series) are not listed there. Use "web page + regex" for them.
- **Reolink**: set the hardware version (app → Device info), because one product can have several revisions.
- **Apple**: versions come from ipsw.me (a service independent of Apple). The newest release that Apple
  still signs is used for comparison.
- **UniFi / Reolink / Synology / FRITZ!** also have native HA integrations. This integration is useful
  when you don't want to set those up or don't want to give them your credentials.

### Not supported, and why
- **HP (BIOS)**: HP catalogs are CAB files with LZX compression, which can't be unpacked without an extra library.
- **Google Pixel**: the OTA page requires accepting Google's terms.
- **Lenovo tablets, Amazon Fire, Xiaomi**: no public version source.
- **Shelly, Philips Hue**: the native HA integrations already show available updates without credentials.

## After upgrading a device manually
- **Settings → Devices & services → Firmware Watch → (entry) → Configure** and change the version, or
- use the `firmware_watch.set_installed_version` action (without `version` it stores the newest known version):

```yaml
action: firmware_watch.set_installed_version
target:
  entity_id: update.nas
```

To check right away, call `homeassistant.update_entity` on the entity.

## Installation

**HACS (recommended)**
1. HACS → ⋮ menu → *Custom repositories* → URL `https://github.com/samul69/ha-firmware-watch`, type **Integration**.
2. Search for "Firmware Watch" → *Download*.
3. Restart Home Assistant.

**Manual**
1. Copy `custom_components/firmware_watch` to `/config/custom_components/` (Samba / File editor / SSH).
2. Restart Home Assistant.

**Then**
1. **Settings → Devices & services → Add integration → Firmware Watch**. Repeat for each device.

Requires Home Assistant 2025.8 or newer.

## Example automation

```yaml
triggers:
  - trigger: state
    entity_id: [update.nas, update.router]
    from: "off"
    to: "on"
actions:
  - action: notify.mobile_app_phone
    data:
      title: "New firmware: {{ trigger.to_state.attributes.friendly_name }}"
      message: >-
        {{ trigger.to_state.attributes.installed_version }} →
        {{ trigger.to_state.attributes.latest_version }}
```

## Adding a vendor
In `providers.py`, add a class that inherits from `Provider`, with `fields` and `async_latest()`
(and `version_key()` if needed). Register it in `PROVIDERS`, add `async_step_<key>` in `config_flow.py`,
and regenerate the translations: `python tools/gen_translations.py custom_components/firmware_watch`.
To test all sources live: `python tools/test_providers.py`.

## License
MIT
