"""Firmware sources ("providers").

Each provider knows how to find the newest public firmware version for a
device on the vendor's website / public API. Nothing here logs in to the
device itself - the installed version comes from the user's configuration.

This module depends only on aiohttp so it can be tested outside Home Assistant.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import aiohttp

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
TIMEOUT = aiohttp.ClientTimeout(total=30)


class ProviderError(Exception):
    """Raised when the latest version cannot be determined."""


@dataclass
class Release:
    """Newest firmware found on the vendor side."""

    version: str
    release_url: str | None = None
    summary: str | None = None
    published: str | None = None


@dataclass
class Field:
    """A provider-specific configuration field."""

    key: str
    kind: str = "text"  # text | bool | select
    required: bool = True
    default: Any = None
    options: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


async def _get_text(session: aiohttp.ClientSession, url: str, **kw) -> str:
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "en;q=0.9"}
    headers.update(kw.pop("headers", {}))
    try:
        async with session.get(url, headers=headers, timeout=TIMEOUT, **kw) as resp:
            if resp.status >= 400:
                raise ProviderError(f"HTTP {resp.status} for {url}")
            return await resp.text(errors="replace")
    except (aiohttp.ClientError, TimeoutError) as err:
        raise ProviderError(f"Request to {url} failed: {err}") from err


async def _get_json(session: aiohttp.ClientSession, url: str, **kw) -> Any:
    text = await _get_text(session, url, **kw)
    try:
        return json.loads(text)
    except ValueError as err:
        raise ProviderError(f"Invalid JSON from {url}") from err


def _strip_html(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\s*\n\s*", "\n", text).strip()


def _short(text: str | None, limit: int = 255) -> str | None:
    if not text:
        return None
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def numeric_key(version: str) -> tuple[int, ...]:
    """Generic comparison key: all integer groups in order."""
    return tuple(int(n) for n in re.findall(r"\d+", version or ""))


_DATE_PATTERNS = (
    r"(?<!\d)(20\d{2})-(\d{2})-(\d{2})(?!\d)",  # 2025-10-30
    r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)",  # 20251030
    r"(?<!\d)(\d{2})(\d{2})(\d{2})\d{2}(?!\d)",  # 25103014 (YYMMDDHH, e.g. Deco)
    r"(?<!\d)(\d{2})(\d{2})(\d{2})(?!\d)",  # 251030
)


def date_key(version: str) -> tuple[int, ...]:
    """Key based on a build date found in the string (several TP-Link styles)."""
    for pattern in _DATE_PATTERNS:
        for m in re.finditer(pattern, version or ""):
            year, month, day = m.groups()
            if len(year) == 2:
                year = "20" + year
            if 1 <= int(month) <= 12 and 1 <= int(day) <= 31:
                return (int(f"{year}{month}{day}"),)
    return numeric_key(version)


# --------------------------------------------------------------------------
# base
# --------------------------------------------------------------------------


class Provider:
    """Base provider."""

    key: str = ""
    manufacturer: str = ""
    fields: list[Field] = []

    def model(self, conf: dict[str, Any]) -> str | None:
        return conf.get("model")

    def version_key(self, version: str) -> tuple[int, ...]:
        return numeric_key(version)

    def is_newer(self, latest: str, installed: str) -> bool:
        lk, ik = self.version_key(latest), self.version_key(installed)
        if lk and ik:
            return lk > ik
        return latest.strip() != installed.strip()

    async def async_latest(
        self, session: aiohttp.ClientSession, conf: dict[str, Any]
    ) -> Release:
        raise NotImplementedError


# --------------------------------------------------------------------------
# Synology (DSM / SRM / BSM) - public support API
# --------------------------------------------------------------------------


class SynologyProvider(Provider):
    key = "synology"
    manufacturer = "Synology"
    fields = [Field("model"), Field("region", default="en-global", required=False)]

    def version_key(self, version: str) -> tuple[int, ...]:
        # "7.2.2-72806 Update 3" -> (72806, 3); build number is monotonic.
        if m := re.search(r"-(\d{4,6})", version or ""):
            nano = re.search(r"update\s*(\d+)", version, re.I)
            return (int(m.group(1)), int(nano.group(1)) if nano else 0)
        return numeric_key(version)

    async def async_latest(self, session, conf):
        model = conf["model"].strip()
        region = (conf.get("region") or "en-global").strip()
        installed = conf.get("installed_version") or "7.0"
        nums = numeric_key(installed) + (7, 0)

        async def fetch(major, minor):
            url = (
                "https://www.synology.com/api/support/findDownloadInfo"
                f"?lang={region}&product={quote(model)}&major={major}&minor={minor}"
            )
            data = await _get_json(session, url)
            if not data.get("success"):
                raise ProviderError(f"Synology does not know model {model!r}")
            info = data.get("info") or {}
            if not info.get("pubVers"):
                raise ProviderError(f"No public OS versions for {model!r}")
            return info

        info = await fetch(nums[0], nums[1])
        newest = info["pubVers"][0]
        # The "system" section (with Update N info) follows the requested
        # major.minor - ask again for the newest train.
        if (newest.get("major"), newest.get("minor")) != (nums[0], nums[1]):
            info = await fetch(newest.get("major"), newest.get("minor"))
            newest = info["pubVers"][0]
        version = re.sub(r"-\d+-NanoPacked$", "", newest["version"])
        build = str(newest.get("build"))

        # Nano ("Update N") releases are reported in the "system" section.
        os_name = "DSM"
        for tab in (info.get("system") or {}).get("detail", []):
            for item in tab.get("items", []):
                if str(item.get("build_num")) == build and item.get("latest_nano"):
                    version = f"{version} Update {item['latest_nano']}"
                    os_name = item.get("key") or os_name
        model_q = quote(model)
        return Release(
            version=version,
            release_url=f"https://www.synology.com/{region}/releaseNote/{os_name}?model={model_q}",
        )


# --------------------------------------------------------------------------
# TP-Link Omada (routers, switches, APs) - support.omadanetworks.com
# --------------------------------------------------------------------------

_OMADA_FW_RE = re.compile(
    r"Firmware Version:(?:\s|<[^>]{0,40}>|&nbsp;)*(\d+\.\d+\.\d+\s+Build\s+\d{8})",
    re.I,
)


def _unescape_js(text: str) -> str:
    return (
        text.replace("\\u003C", "<")
        .replace("\\u003E", ">")
        .replace("\\u002F", "/")
        .replace('\\"', '"')
        .replace("\\n", "\n")
    )


class OmadaProvider(Provider):
    key = "omada"
    manufacturer = "TP-Link Omada"
    fields = [
        Field("model"),
        Field("region", default="en", required=False),
        Field("hardware_version", required=False),
    ]

    def version_key(self, version: str) -> tuple[int, ...]:
        if m := re.search(r"(\d+)\.(\d+)\.(\d+)\s*Build\s*(\d{8})", version or "", re.I):
            return tuple(int(x) for x in m.groups())
        if m := re.search(r"(\d+)\.(\d+)\.(\d+)", version or ""):
            return tuple(int(x) for x in m.groups())
        return numeric_key(version)

    async def async_latest(self, session, conf):
        slug = conf["model"].strip().lower().replace(" ", "-")
        region = (conf.get("region") or "en").strip().strip("/")
        hw = (conf.get("hardware_version") or "").strip().lstrip("vV")
        url = f"https://support.omadanetworks.com/{region}/product/{slug}/"
        page = _unescape_js(await _get_text(session, url))

        matches = list(_OMADA_FW_RE.finditer(page))
        if not matches:
            raise ProviderError(f"No firmware found on {url}")
        candidates: list[tuple[tuple, str, str]] = []
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else m.end() + 3000
            section = _strip_html(page[m.start() : min(end, m.end() + 3000)])
            if hw and not re.search(rf"\)\s*V?{re.escape(hw)}\b", section):
                continue
            ver = re.sub(r"\s+", " ", m.group(1))
            candidates.append((self.version_key(ver), ver, section))
        if not candidates:
            raise ProviderError(f"No firmware for hardware version {hw} on {url}")
        _, ver, section = max(candidates)
        return Release(version=ver, release_url=url, summary=_short(section))


# --------------------------------------------------------------------------
# TP-Link consumer (Archer, Deco, ...) - www.tp-link.com/<region>/support/download
# --------------------------------------------------------------------------

_TPL_BLOCK_RE = re.compile(
    r'class="download-resource-name"[^>]*>\s*<p>([^<]+)</p>(.*?)</table>', re.S
)


class TPLinkProvider(Provider):
    key = "tplink"
    manufacturer = "TP-Link"
    fields = [
        Field("model"),
        Field("hardware_version", required=False),
        Field("region", default="en", required=False),
    ]

    def version_key(self, version: str) -> tuple[int, ...]:
        return date_key(version)

    async def async_latest(self, session, conf):
        slug = conf["model"].strip().lower().replace(" ", "-")
        region = (conf.get("region") or "en").strip().strip("/")
        hw = (conf.get("hardware_version") or "").strip().lower().lstrip("v")
        url = f"https://www.tp-link.com/{region}/support/download/{slug}/"
        if hw:
            url += f"v{hw}/"
        page = await _get_text(session, url)
        start = page.find('id="tabpanel-Firmware"')
        if start < 0:
            start = page.find('data-id="Firmware"')
        if start < 0:
            raise ProviderError(f"No firmware section on {url}")
        page = page[start:]

        candidates = []
        for name, body in _TPL_BLOCK_RE.findall(page):
            name = html.unescape(name).strip()
            m = re.search(r"_V(\d+(?:\.\d+)?)_(.+)$", name)
            if not m:
                continue
            if hw and m.group(1).split(".")[0] != hw.split(".")[0]:
                continue
            ver = m.group(2).strip()
            date = re.search(r"(\d{4})-(\d{2})-(\d{2})", body)
            published = "-".join(date.groups()) if date else None
            key = (int("".join(date.groups())),) if date else date_key(ver)
            summary = _short(_strip_html(body.split("</tr>", 1)[-1]))
            candidates.append((key, ver, published, summary))
        if not candidates:
            raise ProviderError(
                f"No firmware for hardware {('V' + hw) if hw else '?'} on {url} "
                "(TP-Link may redirect to another hardware version)"
            )
        _, ver, published, summary = max(candidates)
        # Make sure the date is comparable with "x.y.z Build YYYYMMDD" installs.
        dk = date_key(ver)
        if published and not (len(dk) == 1 and dk[0] >= 20000101):
            ver = f"{ver} ({published})"
        return Release(version=ver, release_url=url, summary=summary, published=published)


# --------------------------------------------------------------------------
# MikroTik RouterOS
# --------------------------------------------------------------------------


class MikroTikProvider(Provider):
    key = "mikrotik"
    manufacturer = "MikroTik"
    fields = [
        Field("model", required=False),
        Field("channel", kind="select", default="stable",
              options=["stable", "long-term", "testing", "development"]),
        Field("major", default="7", required=False),
    ]

    async def async_latest(self, session, conf):
        channel = conf.get("channel") or "stable"
        major = str(conf.get("major") or "7").strip()
        url = f"https://upgrade.mikrotik.com/routeros/NEWESTa{major}.{channel}"
        text = (await _get_text(session, url)).strip()
        if not text:
            raise ProviderError(f"Empty answer from {url}")
        return Release(
            version=text.split()[0],
            release_url="https://mikrotik.com/download/changelogs",
        )


# --------------------------------------------------------------------------
# GitHub releases (OpenWrt builds, open firmware, ESPHome projects, ...)
# --------------------------------------------------------------------------


class GitHubProvider(Provider):
    key = "github"
    manufacturer = "GitHub"
    fields = [
        Field("repository"),
        Field("model", required=False),
        Field("include_prereleases", kind="bool", default=False, required=False),
    ]

    async def async_latest(self, session, conf):
        repo = conf["repository"].strip().strip("/")
        repo = re.sub(r"^https?://github\.com/", "", repo)
        headers = {"Accept": "application/vnd.github+json"}
        if conf.get("include_prereleases"):
            data = await _get_json(
                session, f"https://api.github.com/repos/{repo}/releases?per_page=10",
                headers=headers,
            )
            data = [r for r in data if not r.get("draft")]
            if not data:
                raise ProviderError(f"No releases in {repo}")
            rel = data[0]
        else:
            rel = await _get_json(
                session, f"https://api.github.com/repos/{repo}/releases/latest",
                headers=headers,
            )
        tag = rel.get("tag_name") or rel.get("name")
        if not tag:
            raise ProviderError(f"No release tag in {repo}")
        return Release(
            version=re.sub(r"^[vV](?=\d)", "", tag),
            release_url=rel.get("html_url"),
            summary=_short(rel.get("body")),
            published=(rel.get("published_at") or "")[:10] or None,
        )


# --------------------------------------------------------------------------
# Generic: any web page + regular expression
# --------------------------------------------------------------------------


class WebRegexProvider(Provider):
    key = "web_regex"
    manufacturer = None
    fields = [
        Field("url"),
        Field("regex"),
        Field("pick", kind="select", default="highest", options=["highest", "first"]),
        Field("manufacturer", required=False),
        Field("model", required=False),
    ]

    async def async_latest(self, session, conf):
        url = conf["url"].strip()
        try:
            pattern = re.compile(conf["regex"], re.I | re.S)
        except re.error as err:
            raise ProviderError(f"Invalid regex: {err}") from err
        page = await _get_text(session, url)
        found = []
        for m in pattern.finditer(page):
            ver = m.group(1) if m.groups() else m.group(0)
            ver = re.sub(r"\s+", " ", html.unescape(ver)).strip()
            if ver:
                found.append(ver)
        if not found:
            raise ProviderError(f"Regex did not match anything on {url}")
        ver = found[0] if conf.get("pick") == "first" else max(found, key=self.version_key)
        return Release(version=ver, release_url=url)


# --------------------------------------------------------------------------
# Generic: JSON endpoint + dotted path
# --------------------------------------------------------------------------


def _json_path(data: Any, path: str) -> Any:
    for part in [p for p in re.split(r"\.|\[|\]", path) if p != ""]:
        if isinstance(data, list):
            data = data[int(part)]
        elif isinstance(data, dict):
            data = data[part]
        else:
            raise KeyError(part)
    return data


class JsonProvider(Provider):
    key = "json"
    manufacturer = None
    fields = [
        Field("url"),
        Field("json_path"),
        Field("manufacturer", required=False),
        Field("model", required=False),
    ]

    async def async_latest(self, session, conf):
        url = conf["url"].strip()
        data = await _get_json(session, url)
        try:
            value = _json_path(data, conf["json_path"].strip())
        except (KeyError, IndexError, ValueError) as err:
            raise ProviderError(f"Path {conf['json_path']!r} not found: {err}") from err
        if isinstance(value, (dict, list)) or value is None:
            raise ProviderError(f"Path {conf['json_path']!r} is not a version string")
        return Release(version=str(value).strip(), release_url=url)


# --------------------------------------------------------------------------
# Dell BIOS - Dell Command Update catalogs on downloads.dell.com
# --------------------------------------------------------------------------


async def _get_bytes(session: aiohttp.ClientSession, url: str) -> bytes:
    try:
        async with session.get(url, headers={"User-Agent": USER_AGENT},
                               timeout=aiohttp.ClientTimeout(total=120)) as resp:
            if resp.status >= 400:
                raise ProviderError(f"HTTP {resp.status} for {url}")
            return await resp.read()
    except (aiohttp.ClientError, TimeoutError) as err:
        raise ProviderError(f"Request to {url} failed: {err}") from err


def _decode_xml(raw: bytes) -> str:
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    return raw.decode("utf-8-sig", errors="replace")


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


class DellBiosProvider(Provider):
    key = "dell"
    manufacturer = "Dell"
    fields = [Field("model")]
    _index_url = "https://downloads.dell.com/catalog/CatalogIndexPC.cab"

    async def async_latest(self, session, conf):
        from .cab import CabError, extract_first  # local import: optional helper

        wanted = conf["model"].strip()
        is_sysid = re.fullmatch(r"[0-9A-Fa-f]{4}", wanted) is not None
        try:
            index = _decode_xml(extract_first(await _get_bytes(session, self._index_url)))
        except CabError as err:
            raise ProviderError(f"Dell catalog index: {err}") from err

        path = None
        for gm in re.finditer(r"<GroupManifest\b.*?</GroupManifest>", index, re.S):
            block = gm.group(0)
            hit = False
            for brand, models in re.findall(
                r"<Brand\b[^>]*>\s*<Display[^>]*><!\[CDATA\[(.*?)\]\]></Display>(.*?)</Brand>",
                block, re.S,
            ):
                for sysid, name in re.findall(
                    r'<Model systemID="([^"]+)"[^>]*>\s*<Display[^>]*><!\[CDATA\[(.*?)\]\]>',
                    models, re.S,
                ):
                    if is_sysid:
                        hit |= sysid.upper() == wanted.upper()
                    else:
                        hit |= _norm(wanted) in (_norm(name), _norm(f"{brand} {name}"))
            if hit:
                latest = re.search(r'latest="([^"]+)"', block)
                mi = None
                if latest:
                    mi = re.search(
                        rf'<ManifestInformation id="{re.escape(latest.group(1))}"[^>]*path="([^"]+)"',
                        block,
                    )
                mi = mi or re.search(r'<ManifestInformation\b[^>]*path="([^"]+)"', block)
                if mi:
                    path = mi.group(1)
                    break
        if not path:
            raise ProviderError(
                f"Model {wanted!r} not found in Dell catalog "
                "(use the name as in Dell support, e.g. 'Latitude 5440', or the 4-digit system ID)"
            )
        try:
            catalog = _decode_xml(
                extract_first(await _get_bytes(session, f"https://downloads.dell.com/{path}"))
            )
        except CabError as err:
            raise ProviderError(f"Dell model catalog: {err}") from err

        best = None
        for m in re.finditer(r"<SoftwareComponent\b(.*?)</SoftwareComponent>", catalog, re.S):
            body = m.group(1)
            if '<ComponentType value="BIOS"' not in body:
                continue
            ver = re.search(r'vendorVersion="([^"]+)"', body)
            if not ver:
                continue
            rel_id = re.search(r'releaseID="([^"]+)"', body)
            date = re.search(r'releaseDate="([^"]+)"', body)
            name = re.search(r"<Name>\s*<Display[^>]*><!\[CDATA\[(.*?)\]\]>", body, re.S)
            cand = (self.version_key(ver.group(1)), ver.group(1),
                    rel_id.group(1) if rel_id else None,
                    date.group(1) if date else None, name.group(1) if name else None)
            if best is None or cand[0] > best[0]:
                best = cand
        if not best:
            raise ProviderError(f"No BIOS in Dell catalog for {wanted!r}")
        _, ver, rel_id, date, name = best
        return Release(
            version=ver,
            release_url=(f"https://www.dell.com/support/home/drivers/driversdetails?driverid={rel_id}"
                         if rel_id else None),
            summary=name,
            published=date,
        )


# --------------------------------------------------------------------------
# Lenovo BIOS (ThinkPad / ThinkCentre / ThinkStation) - System Update catalog
# --------------------------------------------------------------------------


class LenovoBiosProvider(Provider):
    key = "lenovo"
    manufacturer = "Lenovo"
    fields = [
        Field("machine_type"),
        Field("os", kind="select", default="win11", options=["win11", "win10"]),
        Field("model", required=False),
    ]

    def model(self, conf):
        return conf.get("model") or conf.get("machine_type")

    def version_key(self, version: str) -> tuple[int, ...]:
        # Lenovo BIOS IDs end in a two-digit build number:
        #   Think:    "N3QET52W (1.52)", "N3QET52W", "1.52"   -> (52,)
        #   consumer: "PQCN32WW", "HHCN37WW"                 -> (32,), (37,)
        v = (version or "").upper()
        if m := re.search(r"\d+\.(\d+)", v):
            return (int(m.group(1)),)
        if m := re.search(r"(\d{2})WW?\b", v):
            return (int(m.group(1)),)
        return numeric_key(version)

    async def async_latest(self, session, conf):
        mt = conf["machine_type"].strip().upper()[:4]
        os_name = "Win10" if str(conf.get("os") or "").lower() == "win10" else "Win11"
        url = f"https://download.lenovo.com/catalog/{mt}_{os_name}.xml"
        catalog = await _get_text(session, url)
        locations = re.findall(
            r"<location>([^<]+)</location>\s*<category>BIOS UEFI</category>", catalog
        )
        if not locations:
            raise ProviderError(f"No BIOS package in {url} (check machine type, e.g. 21HD)")
        best = None
        for loc in locations:
            pkg = await _get_text(session, loc.strip())
            ver = re.search(r'<Package\b[^>]*\bversion="([^"]+)"', pkg)
            if not ver:
                continue
            date = re.search(r"<ReleaseDate>([^<]+)</ReleaseDate>", pkg)
            title = re.search(r'<Desc id="EN">([^<]+)</Desc>', pkg)
            readme = re.search(r"<Readme[^>]*>\s*<File[^>]*>\s*<Name>([^<]+)</Name>", pkg)
            readme_url = loc.rsplit("/", 1)[0] + "/" + readme.group(1) if readme else None
            cand = (self.version_key(ver.group(1)), ver.group(1),
                    date.group(1) if date else None,
                    html.unescape(title.group(1)) if title else None, readme_url)
            if best is None or cand[0] > best[0]:
                best = cand
        if not best:
            raise ProviderError(f"Could not read BIOS version from {url}")
        _, ver, date, title, readme_url = best
        return Release(version=ver, release_url=readme_url, summary=title, published=date)


# --------------------------------------------------------------------------
# Samsung Galaxy (phones / tablets) - public FOTA version.xml
# --------------------------------------------------------------------------


class SamsungProvider(Provider):
    key = "samsung"
    manufacturer = "Samsung"
    fields = [Field("model"), Field("csc", default="EUX")]

    @staticmethod
    def _pda(version: str) -> str:
        # Accepts "X710XXU5CYJ3", "X710XXU5CYJ3/X710OXM5CYJ3/..." or the full
        # build number "UP1A.231005.007.X710XXU5CYJ3".
        tokens = re.findall(r"[A-Z0-9]{9,}", (version or "").upper())
        return tokens[0] if "/" in (version or "") else (tokens[-1] if tokens else "")

    def version_key(self, version: str) -> tuple[int, ...]:
        # last 5 chars: bootloader rev, major, year, month, build
        pda = self._pda(version)
        return tuple(ord(c) for c in pda[-5:]) if len(pda) >= 5 else ()

    async def async_latest(self, session, conf):
        model = conf["model"].strip().upper()
        if not model.startswith("SM-"):
            model = "SM-" + model
        csc = (conf.get("csc") or "EUX").strip().upper()
        url = f"https://fota-cloud-dn.ospserver.net/firmware/{csc}/{model}/version.xml"
        text = await _get_text(session, url)
        m = re.search(r"<latest[^>]*>([^<]+)</latest>", text)
        if not m:
            raise ProviderError(f"No firmware for {model}/{csc} in {url}")
        pda = m.group(1).split("/")[0].strip()
        android = re.search(r'<latest[^>]*\bo="(\d+)"', text)
        return Release(
            version=pda,
            release_url="https://security.samsungmobile.com/workScope.smsb",
            summary=f"Android {android.group(1)}" if android else None,
        )


# --------------------------------------------------------------------------
# AVM FRITZ! (Box, Repeater, Powerline, DECT, Smart) - download.avm.de
# --------------------------------------------------------------------------

_AVM_CATEGORIES = {
    "fritzbox": "fritzbox",
    "fritzrepeater": "fritzwlan",
    "fritzwlan": "fritzwlan",
    "fritzpowerline": "fritzpowerline",
    "fritzdect": "fritzdect",
    "fritzsmart": "fritzsmart",
}


class AvmProvider(Provider):
    key = "avm"
    manufacturer = "AVM"
    fields = [
        Field("model"),
        Field("region", kind="select", default="other", options=["other", "deutschland"]),
    ]

    def version_key(self, version: str) -> tuple[int, ...]:
        # "FRITZ!OS 8.20" -> (8, 20); "164.08.20" (support data) -> (8, 20)
        nums = numeric_key(re.sub(r"(?i)fritz!?\s*(box|os)?\s*\d{3,5}\b", "", version or ""))
        nums = nums or numeric_key(version)
        if len(nums) >= 3 and nums[0] >= 100:
            nums = nums[1:]
        return nums

    async def async_latest(self, session, conf):
        slug = conf["model"].strip().lower()
        slug = re.sub(r"[!\s_]+", "-", slug).replace("fritz-", "fritz").strip("-")
        region = conf.get("region") or "other"
        prefix = slug.split("-")[0]
        cats = [_AVM_CATEGORIES[prefix]] if prefix in _AVM_CATEGORIES else list(
            dict.fromkeys(_AVM_CATEGORIES.values())
        )
        last_err: Exception | None = None
        for cat in cats:
            base = f"https://download.avm.de/{cat}/{slug}/{region}/fritz.os/"
            for name in ("info_en.txt", "info.txt", "info_de.txt"):
                try:
                    text = await _get_text(session, base + name)
                except ProviderError as err:
                    last_err = err
                    continue
                ver = re.search(r"(?:Version|Versión)\s*:\s*(?:FRITZ!OS\s*)?([\d.]+)", text)
                if not ver:
                    continue
                date = re.search(r"(?:Release date|Datum|Release-Datum)\s*:\s*([\d./-]+)", text)
                return Release(
                    version=ver.group(1),
                    release_url=base + name,
                    published=date.group(1) if date else None,
                )
        raise ProviderError(
            f"FRITZ! product {slug!r} not found on download.avm.de "
            f"(use the folder name, e.g. fritzbox-7590, fritzrepeater-3000-ax): {last_err}"
        )


# --------------------------------------------------------------------------
# Reolink cameras, doorbells, NVRs - public download center API
# --------------------------------------------------------------------------


class ReolinkProvider(Provider):
    key = "reolink"
    manufacturer = "Reolink"
    fields = [Field("model"), Field("hardware_version", required=False)]
    _base = "https://reolink.com/wp-json/reo-v2/download"

    async def async_latest(self, session, conf):
        wanted = conf["model"].strip()
        hw = (conf.get("hardware_version") or "").strip()
        if wanted.isdigit():
            pid = int(wanted)
        else:
            products = (await _get_json(session, f"{self._base}/product/selection-list")).get("data") or []
            if hw:  # hardware version alone identifies the product best
                by_hw = [p for p in products
                         if any(_norm(h["title"]) == _norm(hw) for h in p.get("hardwareVersions", []))]
                if by_hw:
                    products = by_hw
            exact = [p for p in products if _norm(p["title"]) == _norm(wanted)]
            partial = [p for p in products if _norm(wanted) in _norm(p["title"])]
            found = exact or partial
            if not found:
                raise ProviderError(f"Reolink product {wanted!r} not found")
            if len(found) > 1 and not exact:
                names = ", ".join(p["title"] for p in found[:6])
                raise ProviderError(
                    f"{wanted!r} matches several products ({names}) - use the full name "
                    "or set the hardware version"
                )
            pid = found[0]["id"]
        data = (await _get_json(session, f"{self._base}/firmware/?dlProductId={pid}")).get("data") or []
        best = None
        for prod in data:
            for fw in prod.get("firmwares", []):
                hws = [h.get("title", "") for h in fw.get("hardwareVersion", [])]
                if hw and not any(_norm(h) == _norm(hw) for h in hws):
                    continue
                cand = (self.version_key(fw["version"]), fw, prod.get("url"))
                if best is None or cand[0] > best[0]:
                    best = cand
        if not best:
            raise ProviderError(f"No firmware for Reolink product {wanted!r} {hw}")
        _, fw, url = best
        published = None
        if fw.get("displayTime"):
            from datetime import datetime, timezone
            published = datetime.fromtimestamp(fw["displayTime"] / 1000, timezone.utc).date().isoformat()
        return Release(
            version=fw["version"],
            release_url=url or "https://reolink.com/download-center/",
            summary=_short(_strip_html(fw.get("new") or "")),
            published=published,
        )


# --------------------------------------------------------------------------
# Ubiquiti UniFi (APs, switches, consoles, cameras, NVRs)
# --------------------------------------------------------------------------


class UniFiProvider(Provider):
    key = "unifi"
    manufacturer = "Ubiquiti"
    fields = [
        Field("platform"),
        Field("product", default="unifi-firmware"),
        Field("channel", kind="select", default="release", options=["release", "release-candidate", "beta"]),
        Field("model", required=False),
    ]

    def model(self, conf):
        return conf.get("model") or conf.get("platform")

    def version_key(self, version: str) -> tuple[int, ...]:
        # "6.8.2+15592" / "6.0.17+7bcad58" -> compare the release part only
        return numeric_key(re.split(r"[+\-]", (version or "").lstrip("vV"), maxsplit=1)[0])

    async def async_latest(self, session, conf):
        product = (conf.get("product") or "unifi-firmware").strip()
        platform = conf["platform"].strip()
        channel = conf.get("channel") or "release"
        url = ("https://fw-update.ubnt.com/api/firmware-latest"
               f"?filter=eq~~product~~{quote(product)}&filter=eq~~channel~~{quote(channel)}"
               f"&filter=eq~~platform~~{quote(platform)}")
        items = ((await _get_json(session, url)).get("_embedded") or {}).get("firmware") or []
        if not items:
            raise ProviderError(f"No UniFi firmware for {product}/{platform} ({channel})")
        fw = max(items, key=lambda f: self.version_key(f.get("version", "")))
        return Release(
            version=re.sub(r"^v", "", fw["version"]),
            release_url="https://community.ui.com/releases",
            published=(fw.get("created") or "")[:10] or None,
        )


# --------------------------------------------------------------------------
# OpenWrt
# --------------------------------------------------------------------------


class OpenWrtProvider(Provider):
    key = "openwrt"
    manufacturer = "OpenWrt"
    fields = [
        Field("model", required=False),
        Field("channel", kind="select", default="stable", options=["stable", "oldstable"]),
    ]

    async def async_latest(self, session, conf):
        data = await _get_json(session, "https://downloads.openwrt.org/.versions.json")
        key = "oldstable_version" if conf.get("channel") == "oldstable" else "stable_version"
        ver = data.get(key)
        if not ver:
            raise ProviderError("OpenWrt version list has no stable version")
        major = ".".join(ver.split(".")[:2])
        return Release(version=ver, release_url=f"https://openwrt.org/releases/{major}/start")


# --------------------------------------------------------------------------
# Apple iPad / iPhone / Apple-silicon Mac - ipsw.me (signed releases)
# --------------------------------------------------------------------------


class AppleProvider(Provider):
    key = "apple"
    manufacturer = "Apple"
    fields = [Field("model")]

    async def async_latest(self, session, conf):
        wanted = conf["model"].strip()
        ident = wanted
        if not re.fullmatch(r"[A-Za-z]+\d+,\d+", wanted):
            devices = await _get_json(session, "https://api.ipsw.me/v4/devices")
            exact = [d for d in devices if _norm(d["name"]) == _norm(wanted)]
            partial = [d for d in devices if _norm(wanted) in _norm(d["name"])]
            found = exact or partial
            if not found:
                raise ProviderError(f"Apple device {wanted!r} not found on ipsw.me")
            if len(found) > 1 and not exact:
                names = ", ".join(f"{d['name']} ({d['identifier']})" for d in found[:6])
                raise ProviderError(f"{wanted!r} matches several devices: {names}")
            ident = found[0]["identifier"]
        data = await _get_json(session, f"https://api.ipsw.me/v4/device/{quote(ident)}?type=ipsw")
        fws = data.get("firmwares") or []
        signed = [f for f in fws if f.get("signed")] or fws
        if not signed:
            raise ProviderError(f"No firmware for {ident}")
        fw = max(signed, key=lambda f: self.version_key(f.get("version", "")))
        return Release(
            version=fw["version"],
            release_url="https://support.apple.com/en-us/100100",
            summary=f"{data.get('name', ident)} - build {fw.get('buildid')}",
            published=(fw.get("releasedate") or "")[:10] or None,
        )


# --------------------------------------------------------------------------
# ASUS routers (legacy LiveUpdate list - mostly AC / early AX models)
# --------------------------------------------------------------------------


class AsusProvider(Provider):
    key = "asus"
    manufacturer = "ASUS"
    fields = [Field("model")]
    # Only the public release list ("Wireless_SQ" holds internal test builds).
    _urls = ("https://dlcdnets.asus.com/pub/ASUS/LiveUpdate/Release/Wireless/wlan_update_v2.zip",)

    def version_key(self, version: str) -> tuple[int, ...]:
        # 3.0.0.4.386_48377 -> (3,0,0,4,386,48377)
        return numeric_key((version or "").split("-g")[0])

    async def async_latest(self, session, conf):
        model = conf["model"].strip().upper()
        best = None
        for url in self._urls:
            try:
                text = await _get_text(session, url)
            except ProviderError:
                continue
            for line in text.splitlines():
                parts = line.strip().split("#")
                if len(parts) < 5 or parts[0].upper() != model:
                    continue
                fw = next((p[2:] for p in parts if p.startswith("FW") and p[2:].isdigit()), "")
                ext = next((p[3:] for p in parts if p.startswith("EXT")), "")
                if len(fw) < 5:
                    continue
                ver = f"{fw[0]}.{fw[1]}.{fw[2]}.{fw[3]}.{fw[4:]}_{ext.split('-')[0]}"
                if best is None or self.version_key(ver) > self.version_key(best):
                    best = ver
        if not best:
            raise ProviderError(
                f"{model} is not in ASUS LiveUpdate list (newer AX/BE models are not "
                "published there - use the 'web page + regex' source)"
            )
        return Release(version=best, release_url="https://www.asus.com/support/download-center/")


PROVIDERS: dict[str, Provider] = {
    p.key: p
    for p in (
        # network & NAS
        SynologyProvider(),
        AvmProvider(),
        TPLinkProvider(),
        OmadaProvider(),
        UniFiProvider(),
        AsusProvider(),
        MikroTikProvider(),
        OpenWrtProvider(),
        # cameras
        ReolinkProvider(),
        # computers & tablets
        DellBiosProvider(),
        LenovoBiosProvider(),
        AppleProvider(),
        SamsungProvider(),
        # generic
        GitHubProvider(),
        WebRegexProvider(),
        JsonProvider(),
    )
}
