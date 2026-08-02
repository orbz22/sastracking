"""QR code buat jembatan laptop -> aplikasi HP.

Kenapa perlu: halaman tag TikTok sering kosong kalau dibuka di web browser,
tapi normal di aplikasi HP (diuji pada 3 hashtag, 2026-08-02). Jadi verifikasi
manual harus lewat HP — dan mengetik URL panjang itu menyebalkan. Scan QR
langsung membuka hashtag yang tepat di aplikasi.

Pakai `segno`: murni Python, tanpa dependensi biner, dan menghasilkan SVG yang
bisa ditanam langsung ke halaman. Tidak ada permintaan ke layanan QR eksternal —
URL yang dilacak user tidak perlu bocor ke pihak ketiga.
"""

import io
from functools import lru_cache

import segno


@lru_cache(maxsize=512)
def qr_svg(data: str, dark: str = "#101d29") -> str:
    """SVG QR tanpa ukuran tetap — dibesarkan lewat CSS, bukan atribut.

    error='m' (~15% toleransi kerusakan): cukup buat dipindai dari layar, dan
    modulnya tidak sepadat level 'q'/'h' sehingga tetap terbaca di kotak kecil.
    """
    buf = io.BytesIO()
    segno.make(data, error="m").save(
        buf,
        kind="svg",
        xmldecl=False,
        svgns=True,
        scale=1,
        omitsize=True,
        border=2,
        dark=dark,
        light=None,  # transparan: latar diatur CSS (QR wajib di atas putih)
    )
    return buf.getvalue().decode()
