import socket
from typing import Dict, List, Any, Optional

try:
    import psutil
except ImportError:
    psutil = None


def get_network_info(port: int = 8001) -> Dict[str, Any]:
    """Detects server network addresses, prioritizing Windows Mobile Hotspot
    (typically 192.168.137.1) and standard private LAN subnets.
    """
    all_ips: List[str] = []
    hotspot_ip: Optional[str] = None

    if psutil:
        try:
            for iface, addrs in psutil.net_if_addrs().items():
                for addr in addrs:
                    if addr.family == socket.AF_INET and not addr.address.startswith(("127.", "169.254.")):
                        ip = addr.address
                        if ip not in all_ips:
                            all_ips.append(ip)
                        if ip.startswith("192.168.137."):
                            hotspot_ip = ip
        except Exception:
            pass

    if not all_ips:
        try:
            # Protect against hanging DNS queries in offline or sandboxed Windows environments
            old_timeout = socket.getdefaulttimeout()
            socket.setdefaulttimeout(1.0)
            try:
                hostname = socket.gethostname()
                _, _, ips = socket.gethostbyname_ex(hostname)
                for ip in ips:
                    if not ip.startswith(("127.", "169.254.")) and ip not in all_ips:
                        all_ips.append(ip)
                    if ip.startswith("192.168.137.") and not hotspot_ip:
                        hotspot_ip = ip
            finally:
                socket.setdefaulttimeout(old_timeout)
        except Exception:
            pass

    # Fallback if no network interface found
    if not all_ips:
        all_ips = ["127.0.0.1"]

    private_ips = [
        ip for ip in all_ips
        if ip.startswith(("10.", "172.16.", "172.17.", "172.18.", "172.19.",
                          "172.20.", "172.21.", "172.22.", "172.23.", "172.24.",
                          "172.25.", "172.26.", "172.27.", "172.28.", "172.29.",
                          "172.30.", "172.31.", "192.168."))
    ]
    primary_ip = hotspot_ip or (private_ips[0] if private_ips else all_ips[0])

    return {
        "hotspot_detected": hotspot_ip is not None,
        "hotspot_ip": hotspot_ip,
        "primary_ip": primary_ip,
        "all_ips": all_ips,
        "port": port,
        "base_url": f"http://{primary_ip}:{port}",
        "debug_url": f"http://{primary_ip}:{port}/debug",
        "ws_url": f"ws://{primary_ip}:{port}/ws",
    }
