from nonebot_plugin_orm import async_scoped_session, AsyncSession
from nonebot.log import logger
from .model import UserData, LatestRecord, SafehouseRecord
from sqlalchemy.future import select

class UserDataDatabase:
    def __init__(self, session: async_scoped_session|AsyncSession) -> None:
        self.session = session

    async def get_user_data(self, qq: int) -> UserData|None:
        return await self.session.get(UserData, qq)
    
    async def add_user_data(self, external_user_data: UserData) -> bool:
        try:
            await self.session.merge(external_user_data)
        except Exception as e:
            logger.exception(f'插入信息表时发生错误')
            await self.session.rollback()
            return False
        else:
            return True
        
    async def update_user_data(self, external_user_data: UserData) -> bool:
        try:
            await self.session.merge(external_user_data)
        except Exception as e:
            logger.exception(f'更新信息表时发生错误')
            await self.session.rollback()
            return False
        else:
            return True

    async def get_user_data_list(self) -> list[UserData]:
        stmt = select(UserData)
        return list((await self.session.execute(statement=stmt)).scalars().all())
        
    async def commit(self) -> None:
        await self.session.commit()

    # 最新战绩相关方法
    async def get_latest_record(self, qq_id: int) -> LatestRecord|None:
        """获取用户最新战绩记录"""
        return await self.session.get(LatestRecord, qq_id)

    async def update_latest_record(self, latest_record: LatestRecord) -> bool:
        """更新用户最新战绩记录"""
        try:
            await self.session.merge(latest_record)
            return True
        except Exception as e:
            logger.exception(f'更新最新战绩记录时发生错误')
            await self.session.rollback()
            return False

    # 特勤处生产记录相关方法
    async def get_safehouse_records(self, qq_id: int) -> list[SafehouseRecord]:
        """获取用户特勤处生产记录"""
        stmt = select(SafehouseRecord).where(SafehouseRecord.qq_id == qq_id)
        return list((await self.session.execute(statement=stmt)).scalars().all())

    async def update_safehouse_record(self, safehouse_record: SafehouseRecord) -> bool:
        """更新特勤处生产记录"""
        try:
            await self.session.merge(safehouse_record)
            return True
        except Exception as e:
            logger.exception(f'更新特勤处生产记录时发生错误')
            await self.session.rollback()
            return False

    async def delete_safehouse_record(self, qq_id: int, device_id: str) -> bool:
        """删除特勤处生产记录"""
        try:
            stmt = select(SafehouseRecord).where(
                SafehouseRecord.qq_id == qq_id,
                SafehouseRecord.device_id == device_id
            )
            record = (await self.session.execute(statement=stmt)).scalar_one_or_none()
            if record:
                await self.session.delete(record)
            return True
        except Exception as e:
            logger.exception(f'删除特勤处生产记录时发生错误')
            await self.session.rollback()
            return False