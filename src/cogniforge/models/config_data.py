"""ConfigStore 数据模型"""

from pydantic import BaseModel, Field


class EnvironmentData(BaseModel):
    """环境配置数据结构"""

    id: str = Field(description="环境唯一标识符")
    name: str = Field(description="环境名称")
