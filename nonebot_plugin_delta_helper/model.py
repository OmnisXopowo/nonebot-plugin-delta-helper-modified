from sqlalchemy.orm import Mapped, mapped_column
from nonebot_plugin_orm import Model

class UserData(Model):
    qq_id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column()
    access_token: Mapped[str] = mapped_column()
    openid: Mapped[str] = mapped_column()

class LatestRecord(Model):
    """用户最新战绩记录"""
    qq_id: Mapped[int] = mapped_column(primary_key=True)  # 用户QQ号作为主键
    latest_record_id: Mapped[str] = mapped_column()  # 最新战绩ID
