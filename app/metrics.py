"""Hitung metrik viral + tentukan ambang 'sedang viral'. Diisi di M3."""


def compute_velocity(snapshots: list) -> float:
    """Δ views per waktu (24–72 jam). M3."""
    raise NotImplementedError("M3")


def is_viral(trend, snapshots: list) -> bool:
    """True kalau lolos ambang (velocity/volume/engagement). M3."""
    raise NotImplementedError("M3")
