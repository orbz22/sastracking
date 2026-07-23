"""Deteksi gaya editing Level 1 — tebak dari hashtag/sound. Diisi di M6."""

# peta kasar hashtag -> label gaya edit (dilengkapi di M6)
HASHTAG_STYLE_MAP: dict[str, str] = {
    "jedagjedug": "jedag-jedug",
    "slowmo": "slow-mo",
    "transition": "transisi",
    "velocity": "velocity edit",
}


def guess_style(hashtags: list[str]) -> list[str]:
    """Kembalikan label gaya edit dari daftar hashtag. M6."""
    raise NotImplementedError("M6")
