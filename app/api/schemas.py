# app/api/schemas.py
from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict

class AccountSyncRequest(BaseModel):
    email: str = Field(default="", description="Lilith account email")
    # Optional at schema level so the handler can return a plain Arabic message
    # instead of a raw Pydantic 422 array the login modal cannot read.
    password: str = Field(default="", description="Account password")
    user_id: str = Field(default="", description="Tenant Discord user id (injected server-side)")
    bot_id: Optional[str] = Field(default=None, description="Bot unit id to assign this account to")

class CaptchaVerifyRequest(BaseModel):
    model_config = {"populate_by_name": True}
    email: str = Field(..., description="Account email")
    password: str = Field(..., description="Account password")
    user_id: str = Field(default="", description="Tenant Discord user id (injected server-side)")
    captcha_id: str = Field(..., description="captchaId UUID from the CaptchaDialog bridge after solving")
    bot_id: Optional[str] = Field(default=None, description="Bot unit id to assign this account to")

class FinalizeCaptchaRequest(BaseModel):
    model_config = {"populate_by_name": True}
    email: str = Field(..., description="Account email")
    password: str = Field(..., description="Account password")
    user_id: str = Field(default="", description="Tenant Discord user id (injected server-side)")
    ticket: str = Field(..., description="Lilith authentic captcha ticket / token")
    randstr: Optional[str] = Field(default="", description="Optional captcha randstr / challenge")
    bot_id: Optional[str] = Field(default=None, description="Bot unit id to assign this account to")

class CharacterTaskRequest(BaseModel):
    task_name: str = Field("sync_full", description="Task to execute: 'sync_full', 'train', 'gather', 'alliance_help'")
    params: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Optional extra parameters for the task")

class CharacterSettingsRequest(BaseModel):
    model_config = {"populate_by_name": True}
    train_pct: Optional[int] = Field(default=None, description="100 = full capacity, 50 = half")
    train_count_custom: Optional[int] = Field(default=None, description="Custom count (null = use percentage)")
    clear_custom_count: Optional[bool] = Field(default=False, description="Clear custom count back to percentage mode")
    tiers: Optional[Dict[str, Any]] = Field(default=None, description="Per-category tier, e.g. {infantry: 4}")
    gather: Optional[Dict[str, Any]] = Field(default=None, description="Gather filters")
    combat: Optional[Dict[str, Any]] = Field(default=None, description="Barbarian combat settings")
    hospital: Optional[Dict[str, Any]] = Field(default=None, description="Hospital healing settings")
    alliance: Optional[Dict[str, Any]] = Field(default=None, description="Alliance automations")
    daily_claims: Optional[Dict[str, Any]] = Field(default=None, description="Daily claims and quests")
    city: Optional[Dict[str, Any]] = Field(default=None, description="City collection settings")

class CharacterSettingsResponse(BaseModel):
    character_id: int
    role_id: str
    train_pct: int = 100
    train_count_custom: Optional[int] = None
    tiers: Dict[str, Any] = {}
    gather: Dict[str, Any] = {}
    combat: Dict[str, Any] = {}
    hospital: Dict[str, Any] = {}
    alliance: Dict[str, Any] = {}
    daily_claims: Dict[str, Any] = {}
    city: Dict[str, Any] = {}

class CharacterResponse(BaseModel):
    role_id: str
    account_email: Optional[str] = None
    account_id: int
    kingdom_id: int
    name: str
    power: int
    city_level: int
    avatar_url: Optional[str] = None
    alliance_tag: Optional[str] = None
    last_synced: Optional[str] = None
    is_active_cloud: bool = False
    status: Optional[str] = "IDLE"

class AccountResponse(BaseModel):
    id: int
    email: str
    udid: str
    app_uid: Optional[str] = None
    character_count: int = 0
    created_at: Optional[str] = None
    bot_id: Optional[str] = None

class TaskLogResponse(BaseModel):
    id: int
    task_id: str
    role_id: Optional[str] = None
    character_id: Optional[int] = None
    task_type: str
    status: str
    details: Optional[Dict[str, Any]] = None
    timestamp: Optional[str] = None

class DashboardStatsResponse(BaseModel):
    total_accounts: int
    total_characters: int
    total_power: int
    total_tasks_completed: int
    total_tasks_failed: int

class GatherDispatchRequest(BaseModel):
    role_id: str = Field(..., description="Target character role_id")
    food: int = Field(default=1, ge=0, le=5, description="Number of food gather marches")
    wood: int = Field(default=1, ge=0, le=5, description="Number of wood gather marches")
    stone: int = Field(default=1, ge=0, le=5, description="Number of stone gather marches")
    gold: int = Field(default=0, ge=0, le=5, description="Number of gold gather marches")
    max_node_level: str = Field(default="Level 6 and below", description="Node level constraint")
    only_finishable: bool = Field(default=True, description="Only target nodes current army capacity can fully drain")
    skip_partially: bool = Field(default=True, description="Skip nodes partially gathered by others")
    avoid_territory: Optional[bool] = Field(default=True, description="Avoid foreign and enemy alliance territories")
    alliance_tag: Optional[str] = Field(default=None, description="Alliance tag filter")
    city_x: Optional[float] = Field(default=None, description="Stored city X (saved to character settings)")
    city_y: Optional[float] = Field(default=None, description="Stored city Y (saved to character settings)")

class MarchInfo(BaseModel):
    queue_id: int
    cmd_id: Optional[int] = None
    sec_cmd_id: Optional[int] = None
    cmd_name: Optional[str] = "Unassigned"
    type: Optional[str] = "idle"
    target: Optional[str] = "Ready"
    troops: int = 0
    load: int = 0
    node_reserves: int = 0
    status: str = "IDLE"

class GatherStatusResponse(BaseModel):
    active_marches_count: int = 0
    max_queues: int = 5
    total_city_troops: int = 0
    marches: List[MarchInfo] = []
    last_update: Optional[str] = None

class TrainDispatchRequest(BaseModel):
    role_id: str = Field(..., description="Target character role_id")
    train_pct: int = Field(default=100, description="100 = full capacity, 50 = half")
    train_count_custom: Optional[int] = Field(default=None, description="Custom count (null = use percentage)")
    categories: Optional[List[str]] = Field(default_factory=lambda: ["infantry", "cavalry", "archery", "siege"], description="Selected categories")
    tiers: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Selected tier per category: {'infantry': 1, 'cavalry': 1, 'archery': 1, 'siege': 1}")
    auto_collect: bool = Field(default=True, description="Auto-collect completed troops before training")

