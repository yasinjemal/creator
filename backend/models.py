from dataclasses import dataclass
from typing import Optional, Dict, Any

@dataclass
class Brand:
    name: str
    voice: Dict[str, Any]
    assets: Dict[str, Any]

# Additional models (Content, Campaign, Schedule) would be defined similarly.
