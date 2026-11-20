import html
from io import BytesIO
from typing import Dict


def get_role_urls(base_ip: str, port: int = 8001) -> Dict[str, Dict[str, str]]:
    base = f"http://{base_ip}:{int(port)}"
    return {
        "display": {"url": f"{base}/display", "label": "Projector Display"},
        "moderator": {"url": f"{base}/moderator", "label": "Moderator"},
        "admin": {"url": f"{base}/admin", "label": "Admin"},
        "buzzer_a": {"url": f"{base}/buzzer/a?pairing=BUZZ_A", "label": "Buzzer A"},
        "buzzer_b": {"url": f"{base}/buzzer/b?pairing=BUZZ_B", "label": "Buzzer B"},
    }


def generate_qr_svg(data: str, size: int = 256) -> str:
    """Generate a real QR SVG locally, without a CDN or network request."""
    try:
        import qrcode
        from qrcode.image.svg import SvgPathImage
    except ImportError as exc:
        raise RuntimeError("The offline QR dependency 'qrcode' is not installed") from exc

    qr = qrcode.QRCode(version=None, box_size=8, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    image = qr.make_image(image_factory=SvgPathImage)
    output = BytesIO()
    image.save(output)
    svg = output.getvalue().decode("utf-8")
    svg = svg[svg.find("<svg"):]
    return svg.replace("<svg ", f'<svg role="img" aria-label="{html.escape(data)}" ', 1)
