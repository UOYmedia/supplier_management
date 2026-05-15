from datetime import datetime
from pydantic import BaseModel, ConfigDict
from app.models.user import UserRole


class UserCreate(BaseModel):
    username: str
    email: str | None = None
    password: str
    role: UserRole = UserRole.staff


class UserUpdate(BaseModel):
    email: str | None = None
    password: str | None = None
    role: UserRole | None = None
    is_active: bool | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    email: str | None
    role: UserRole
    is_active: bool
    created_at: datetime
