"""Top-level package for CCSDS COP-1."""

from .common.ccsds import ControlWord, Gvcid
from .common.service import CopService, Indication, ServiceInterface

__all__ = ["ControlWord", "CopService", "Gvcid", "Indication", "ServiceInterface"]
