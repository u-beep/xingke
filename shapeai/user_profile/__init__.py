"""用户个人资料管理模块。

管理用户的身高、体重、个人偏好等数据，
支持自动从对话中提取和更新个人信息。
"""

from .profile_store import ProfileStore, UserProfile
from .preference_updater import PreferenceUpdater

__all__ = ["ProfileStore", "UserProfile", "PreferenceUpdater"]
