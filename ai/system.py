"""The "This PC" check: a plain answer about local models before anything is downloaded."""
import ctypes
import os


def total_ram_gb() -> float:
    try:
        if os.name == "nt":
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MEMORYSTATUSEX()
            m.dwLength = ctypes.sizeof(m)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return round(m.ullTotalPhys / 1024 ** 3, 1)
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024 ** 3, 1)
    except Exception:
        return 0.0


def local_model_advice(ram_gb: float) -> str:
    if ram_gb <= 0:
        return "Couldn't check this PC's memory. Local models need about 8 GB of RAM or more."
    if ram_gb < 8:
        return (f"{ram_gb:g} GB of RAM. Local models will be very slow on this PC, so a cloud provider "
                "will work better.")
    if ram_gb < 16:
        return (f"{ram_gb:g} GB of RAM. This PC can run small local models (about 2 to 5 GB). Expect replies "
                "to take 10 to 30 seconds.")
    return (f"{ram_gb:g} GB of RAM. This PC can run medium local models (about 5 to 10 GB). Replies are "
            "slower than cloud providers, and fastest with a supported graphics card.")


def ollama_status(transport=None) -> dict:
    import httpx
    try:
        with httpx.Client(timeout=2.0, transport=transport) as c:
            v = c.get("http://localhost:11434/api/version").json().get("version", "")
        return {"running": True, "version": v}
    except Exception:
        return {"running": False, "version": ""}


def summary(transport=None) -> dict:
    ram = total_ram_gb()
    return {"ram_gb": ram, "advice": local_model_advice(ram), "ollama": ollama_status(transport)}
