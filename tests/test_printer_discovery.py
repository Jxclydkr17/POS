"""
tests/test_printer_discovery.py — Autodetección de impresoras.

Cubre el módulo `app.utils.printer_discovery` y la guarda de plataforma
de `app.utils.print_ticket.print_to_system_printer`.

Los tests son autocontenidos: NO requieren Windows, ni pywin32, ni
libusb, ni una impresora real. Se inyectan módulos falsos en sys.modules
y se parchea `platform.system` para simular cada entorno. Esto hace que
la suite sea determinista en CI (Linux) y valide ambos caminos.
"""

import sys
import types

import pytest

from app.utils import printer_discovery as pd


# ─────────────────────────────────────────────────────────
# Degradación limpia cuando no hay backends (caso Linux/CI)
# ─────────────────────────────────────────────────────────

def test_discover_structure_no_backends(monkeypatch):
    """Sin backends, discover_printers no rompe y devuelve la estructura."""
    monkeypatch.setattr(pd, "_win32print_available", lambda: False)
    monkeypatch.setattr(pd, "_pyusb_available", lambda: False)

    result = pd.discover_printers()

    assert set(result.keys()) == {"platform", "backends", "system", "usb", "notes"}
    assert result["backends"] == {"win32print": False, "pyusb": False}
    assert result["system"] == []
    assert result["usb"] == []
    assert isinstance(result["notes"], list)


def test_list_system_printers_empty_on_non_windows(monkeypatch):
    """En no-Windows, list_system_printers devuelve [] sin tocar backends."""
    monkeypatch.setattr(pd.platform, "system", lambda: "Linux")
    assert pd.list_system_printers() == []


def test_list_usb_printers_empty_without_backend(monkeypatch):
    """Sin backend pyusb/libusb, list_usb_printers devuelve []."""
    monkeypatch.setattr(pd, "_pyusb_available", lambda: False)
    assert pd.list_usb_printers() == []


# ─────────────────────────────────────────────────────────
# Enumeración de impresoras del sistema con win32print falso
# ─────────────────────────────────────────────────────────

def _install_fake_win32print(monkeypatch, printers, default_name=""):
    """Inyecta un módulo win32print falso en sys.modules."""
    fake = types.ModuleType("win32print")
    fake.PRINTER_ENUM_LOCAL = 0x02
    fake.PRINTER_ENUM_CONNECTIONS = 0x04
    fake.PRINTER_ENUM_NAME = 0x08

    def _enum(flags, name, level):
        return printers

    fake.EnumPrinters = _enum
    fake.GetDefaultPrinter = lambda: default_name
    monkeypatch.setitem(sys.modules, "win32print", fake)
    return fake


def test_list_system_printers_windows(monkeypatch):
    """Enumera impresoras y marca la predeterminada; ordena correctamente."""
    monkeypatch.setattr(pd.platform, "system", lambda: "Windows")
    monkeypatch.setattr(pd, "_win32print_available", lambda: True)

    printers = [
        {"pPrinterName": "Microsoft Print to PDF", "pPortName": "PORTPROMPT:",
         "pDriverName": "Microsoft Print To PDF"},
        {"pPrinterName": "EPSON TM-T20II Receipt", "pPortName": "USB001",
         "pDriverName": "EPSON TM-T20II Receipt"},
    ]
    _install_fake_win32print(monkeypatch, printers, default_name="EPSON TM-T20II Receipt")

    result = pd.list_system_printers()

    assert len(result) == 2
    # La predeterminada va primero.
    assert result[0]["name"] == "EPSON TM-T20II Receipt"
    assert result[0]["is_default"] is True
    assert result[0]["port"] == "USB001"
    assert result[1]["name"] == "Microsoft Print to PDF"
    assert result[1]["is_default"] is False


def test_list_system_printers_handles_enum_failure(monkeypatch):
    """Si EnumPrinters lanza, devolvemos [] en vez de propagar."""
    monkeypatch.setattr(pd.platform, "system", lambda: "Windows")
    monkeypatch.setattr(pd, "_win32print_available", lambda: True)

    fake = types.ModuleType("win32print")
    fake.PRINTER_ENUM_LOCAL = 0x02
    fake.PRINTER_ENUM_CONNECTIONS = 0x04

    def _boom(*a, **k):
        raise OSError("spooler caído")

    fake.EnumPrinters = _boom
    fake.GetDefaultPrinter = lambda: ""
    monkeypatch.setitem(sys.modules, "win32print", fake)

    assert pd.list_system_printers() == []


# ─────────────────────────────────────────────────────────
# Escaneo USB con pyusb falso
# ─────────────────────────────────────────────────────────

class _FakeIntf:
    def __init__(self, cls):
        self.bInterfaceClass = cls


class _FakeCfg:
    def __init__(self, intfs):
        self._intfs = intfs

    def __iter__(self):
        return iter(self._intfs)


class _FakeUsbDev:
    def __init__(self, vid, pid, dev_class=0, intf_classes=(0,)):
        self.idVendor = vid
        self.idProduct = pid
        self.bDeviceClass = dev_class
        self.iManufacturer = 1
        self.iProduct = 2
        self._cfgs = [_FakeCfg([_FakeIntf(c) for c in intf_classes])]

    def __iter__(self):
        return iter(self._cfgs)


def _install_fake_pyusb(monkeypatch, devices, strings=None):
    """Inyecta usb.core y usb.util falsos."""
    strings = strings or {}
    usb_pkg = types.ModuleType("usb")
    core = types.ModuleType("usb.core")
    util = types.ModuleType("usb.util")

    core.find = lambda find_all=False: list(devices) if find_all else (devices[0] if devices else None)

    def _get_string(dev, index):
        return strings.get((id(dev), index))

    util.get_string = _get_string

    usb_pkg.core = core
    usb_pkg.util = util
    monkeypatch.setitem(sys.modules, "usb", usb_pkg)
    monkeypatch.setitem(sys.modules, "usb.core", core)
    monkeypatch.setitem(sys.modules, "usb.util", util)


def test_list_usb_printers_filters_printer_class(monkeypatch):
    """Cuando hay clase de impresora declarada, se filtran solo esos."""
    monkeypatch.setattr(pd, "_pyusb_available", lambda: True)

    printer_dev = _FakeUsbDev(0x04b8, 0x0202, intf_classes=(pd._USB_PRINTER_CLASS,))
    other_dev = _FakeUsbDev(0x1234, 0x5678, intf_classes=(0x03,))  # HID, no impresora

    strings = {
        (id(printer_dev), 1): "EPSON",
        (id(printer_dev), 2): "TM-T20II",
    }
    _install_fake_pyusb(monkeypatch, [printer_dev, other_dev], strings)

    result = pd.list_usb_printers(only_printer_class=True)

    assert len(result) == 1
    dev = result[0]
    assert dev["vendor_id"] == "0x04b8"
    assert dev["product_id"] == "0x0202"
    assert dev["vendor_id_int"] == 0x04b8
    assert dev["is_printer_class"] is True
    assert "EPSON" in dev["description"]
    assert "TM-T20II" in dev["description"]


def test_list_usb_printers_returns_all_when_class_unknown(monkeypatch):
    """Si ningún dispositivo declara clase de impresora, se devuelven todos."""
    monkeypatch.setattr(pd, "_pyusb_available", lambda: True)

    d1 = _FakeUsbDev(0x04b8, 0x0202, intf_classes=(0x00,))
    d2 = _FakeUsbDev(0x0519, 0x0001, intf_classes=(0x00,))
    _install_fake_pyusb(monkeypatch, [d1, d2])

    result = pd.list_usb_printers(only_printer_class=True)
    # Ninguno declara clase 0x07 → no filtramos (no escondemos posibles
    # impresoras cuando no se pueden leer las interfaces).
    assert len(result) == 2


def test_list_usb_printers_handles_find_failure(monkeypatch):
    """Si usb.core.find lanza (NoBackendError), devolvemos []."""
    monkeypatch.setattr(pd, "_pyusb_available", lambda: True)

    usb_pkg = types.ModuleType("usb")
    core = types.ModuleType("usb.core")

    def _boom(find_all=False):
        raise RuntimeError("No backend available")

    core.find = _boom
    usb_pkg.core = core
    monkeypatch.setitem(sys.modules, "usb", usb_pkg)
    monkeypatch.setitem(sys.modules, "usb.core", core)

    assert pd.list_usb_printers() == []


# ─────────────────────────────────────────────────────────
# Guarda de plataforma en print_to_system_printer
# ─────────────────────────────────────────────────────────

def test_print_to_system_printer_rejects_non_windows(monkeypatch):
    """En no-Windows debe levantar RuntimeError con mensaje claro."""
    from app.utils import print_ticket

    monkeypatch.setattr(print_ticket.platform, "system", lambda: "Linux")
    with pytest.raises(RuntimeError) as exc:
        print_ticket.print_to_system_printer(b"\x1b@hola", printer_name="X")
    assert "Windows" in str(exc.value)


def test_print_to_system_printer_validates_bytes(monkeypatch):
    """Entrada que no es bytes debe ser rechazada antes del transporte."""
    from app.utils import print_ticket

    monkeypatch.setattr(print_ticket.platform, "system", lambda: "Windows")
    with pytest.raises(TypeError):
        print_ticket.print_to_system_printer("no soy bytes", printer_name="X")