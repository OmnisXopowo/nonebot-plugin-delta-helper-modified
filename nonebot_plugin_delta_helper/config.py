from pydantic import BaseModel


class Config(BaseModel):
    """Plugin Config Here"""
    delta_helper_ai_api_key: str = ""
    delta_helper_ai_base_url: str = ""
    delta_helper_ai_model: str = ""
    delta_helper_ai_proxy: str = ""
    delta_helper_use_card_render: bool = True  # 是否使用卡片渲染
