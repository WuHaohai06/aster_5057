"""Aster adapters for the version-locked QuantaAlpha deployment."""

__all__ = ["QuantaAlphaDataAdapter"]


def __getattr__(name: str):
    if name == "QuantaAlphaDataAdapter":
        from .data_adapter import QuantaAlphaDataAdapter

        return QuantaAlphaDataAdapter
    raise AttributeError(name)
