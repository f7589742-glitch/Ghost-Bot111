import logging
import asyncio
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

async def recall_character_marches(client, role_id: str) -> Dict[str, Any]:
    """
    Manually recalls all field marches for a specific character.
    Triggered ONLY via explicit API request.
    """
    recalled = 0
    state = getattr(client, "state", {})
    marches = state.get("marches", {})
    
    for march_id, march_data in marches.items():
        if march_data.get("status") not in ("RETURNING", "HEADING_HOME", 3):
            # Send Opcode 1013 (Action: Return to City)
            ack = await client.send_packet(1013, {1: str(march_id), 2: 1})
            if ack and ack.get("code") in (0, 1):
                recalled += 1
                
    return {"role_id": role_id, "recalled": recalled, "success": True}
