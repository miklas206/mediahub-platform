"""Bounded read-only inventory. Never opens a device or grants passthrough."""

import json
import re
import time
from pathlib import Path


def block_inventory(root: Path | None):
    """Read sysfs metadata only; never open block nodes or probe filesystems."""
    if root is None or not root.is_dir():
        return {"available": False, "devices": [], "reason": "Block inventory unavailable"}
    try:
        entries = sorted(root.iterdir())[:256]
    except OSError:
        return {"available": False, "devices": [], "reason": "Block inventory inaccessible"}
    devices = []
    for path in entries:
        try:
            serial_file = path / "device" / "serial"
            if not serial_file.is_file():
                serial_file = path / "serial"
            serial = serial_file.read_text().strip()[:256]
            if serial:
                devices.append(
                    {"type": "block", "serial": serial, "location": path.name, "connected": True}
                )
        except OSError:
            continue
    return {"available": True, "devices": devices}


def snapshot_inventory(path):
    try:
        if path.stat().st_size > 1024 * 1024:
            raise ValueError("oversize")
        data = json.loads(path.read_text())
        age = time.time() - data["observedAt"]
        if not 0 <= age <= 90 or data.get("schemaVersion") != 1:
            raise ValueError("stale or unsupported")
        if not isinstance(data.get("devices"), list) or len(data["devices"]) > 256:
            raise ValueError("invalid devices")
        if data.get("scope") != "host-mount-namespace" or data.get("available") is not True:
            raise ValueError("invalid scope")
        return data
    except (OSError, ValueError, KeyError, TypeError):
        return {"available": False, "devices": [], "reason": "Host snapshot unavailable or stale"}


def device_report(usb_root, block_root, requirements, selectors, snapshot=None):
    sources = {
        "usb": usb_inventory(usb_root),
        "block": snapshot_inventory(snapshot) if snapshot else block_inventory(block_root),
    }
    checks = [
        check
        for requirement in requirements
        for check in required_device_health([requirement], selectors, sources[requirement.type])
    ]
    severity = {"healthy": 0, "unknown": 1, "degraded": 2, "critical": 3}
    health = max((check["status"] for check in checks), key=severity.get, default="healthy")
    return {
        "sources": sources,
        "checks": checks,
        "health": health,
        "requiredCount": sum(item.required for item in requirements),
    }


def usb_inventory(root: Path | None):
    if root is None or not root.is_dir():
        return {
            "available": False,
            "devices": [],
            "reason": "USB inventory not configured or unavailable",
        }
    devices = []
    try:
        entries = sorted(root.iterdir())[:256]
    except OSError:
        return {"available": False, "devices": [], "reason": "USB inventory inaccessible"}
    for path in entries:
        try:
            vendor = (path / "idVendor").read_text().strip().lower()
            product = (path / "idProduct").read_text().strip().lower()
            if not all(re.fullmatch(r"[0-9a-f]{4}", value) for value in (vendor, product)):
                continue
            serial = (
                (path / "serial").read_text().strip()[:256] if (path / "serial").exists() else None
            )
            devices.append(
                {
                    "type": "usb",
                    "vendorId": vendor,
                    "productId": product,
                    "serial": serial,
                    "location": path.name,
                    "connected": True,
                }
            )
        except OSError:
            continue
    return {"available": True, "devices": devices}


def required_device_health(requirements, selectors, inventory):
    """Unknown/missing/ambiguous required identity fails closed; no VID-only guesses."""
    checks = []
    for requirement in requirements:
        selector = selectors.get(requirement.selectorRef)
        matches = []
        if selector and inventory.get("available"):
            identity_fields = (
                ("vendorId", "productId", "serial")
                if requirement.type == "usb"
                else ("serial", "uuid", "stableIdentity")
            )
            accepted = {key: selector[key] for key in identity_fields if selector.get(key)}
            valid = (
                all(accepted.get(k) for k in ("vendorId", "productId"))
                if requirement.type == "usb"
                else bool(accepted)
            )
            if valid:
                matches = [
                    device
                    for device in inventory.get("devices", [])
                    if device.get("type") == requirement.type
                    and device.get("connected")
                    and all(device.get(key) == value for key, value in accepted.items())
                ]
        connected = len(matches) == 1
        ready = connected
        if connected and requirement.mountRequired:
            expected_mount = (selector or {}).get("mountPath")
            mounts = [
                mount
                for mount in matches[0].get("mounts", [])
                if not expected_mount or mount.get("path") == expected_mount
            ]
            ready = bool(mounts)
            if requirement.writeRequired:
                ready = (
                    ready
                    and not matches[0].get("readOnly", True)
                    and any(mount.get("readOnly") is False for mount in mounts)
                )
        checks.append(
            {
                "id": requirement.id,
                "connected": connected,
                "status": "healthy"
                if ready
                else requirement.missingHealth
                if requirement.required
                else "unknown",
                "message": "Connected"
                if ready
                else "Required mount unavailable or read-only"
                if connected
                else "Device identity ambiguous"
                if len(matches) > 1
                else "Required device unavailable"
                if requirement.required
                else "Optional device unavailable",
            }
        )
    return checks
