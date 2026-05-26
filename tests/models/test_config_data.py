"""ConfigStore 数据模型单元测试"""

import pytest
from pydantic import ValidationError

from cogniforge.models.config_data import EnvironmentData


class TestEnvironmentData:
    """EnvironmentData 模型测试"""

    def test_required_fields(self):
        """所有必需字段: id, name"""
        data = EnvironmentData(id="env-001", name="测试环境")
        assert data.id == "env-001"
        assert data.name == "测试环境"

    def test_id_required(self):
        """id 是必填字段"""
        with pytest.raises(ValidationError):
            EnvironmentData(name="测试环境")

    def test_name_required(self):
        """name 是必填字段"""
        with pytest.raises(ValidationError):
            EnvironmentData(id="env-001")
