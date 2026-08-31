"""API 路由包。"""

from .auth import router as auth_router
from .chat import router as chat_router
from .tools import router as tools_router
from .knowledge import router as knowledge_router
from .image import router as image_router
from .profile import router as profile_router
from .weight import router as weight_router
from .diet import router as diet_router
from .hydration import router as hydration_router
from .exercise import router as exercise_router
from .exercise_plan import router as exercise_plan_router
from .workout import router as workout_router
from .dashboard import router as dashboard_router
from .goals import router as goals_router
from .feedback import router as feedback_router
from .export import router as export_router
from .takeout import router as takeout_router
from .fridge import router as fridge_router
from .activities import router as activities_router

__all__ = [
    "auth_router",
    "chat_router",
    "image_router",
    "knowledge_router",
    "profile_router",
    "tools_router",
    "weight_router",
    "diet_router",
    "hydration_router",
    "exercise_router",
    "exercise_plan_router",
    "workout_router",
    "dashboard_router",
    "goals_router",
    "feedback_router",
    "export_router",
    "takeout_router",
    "fridge_router",
    "activities_router",
]
