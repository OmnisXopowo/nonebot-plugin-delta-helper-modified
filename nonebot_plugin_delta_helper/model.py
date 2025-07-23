from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import text
from nonebot_plugin_orm import Model

class UserData(Model):
    qq_id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column()
    access_token: Mapped[str] = mapped_column()
    openid: Mapped[str] = mapped_column()
    if_remind_safehouse: Mapped[bool] = mapped_column(default=False, server_default=text('false'))

class LatestRecord(Model):
    """用户最新战绩记录"""
    qq_id: Mapped[int] = mapped_column(primary_key=True)  # 用户QQ号作为主键
    latest_record_id: Mapped[str] = mapped_column()  # 最新战绩ID

class SafehouseRecord(Model):
    """用户特勤处生产记录"""
    qq_id: Mapped[int] = mapped_column(primary_key=True)  # 用户QQ号作为主键
    device_id: Mapped[str] = mapped_column(primary_key=True)  # 设备ID
    object_id: Mapped[int] = mapped_column()  # 生产物品ID
    object_name: Mapped[str] = mapped_column()  # 生产物品名称
    place_name: Mapped[str] = mapped_column()  # 工作台名称
    left_time: Mapped[int] = mapped_column()  # 剩余时间（秒）
    push_time: Mapped[int] = mapped_column()  # 推送时间戳
