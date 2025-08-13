from pydantic import BaseModel


class Config(BaseModel):
    """Plugin Config Here"""
    delta_helper_ai_api_key: str = ""
    delta_helper_ai_base_url: str = ""
    delta_helper_ai_model: str = ""
    delta_helper_ai_proxy: str = ""
    delta_helper_enable_broadcast_record: bool = True
