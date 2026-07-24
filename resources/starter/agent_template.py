"""
Agent 模板 - Supply Chain DocAgent
此文件提供 Agent 的基本结构，参赛者需要填充具体实现。
"""

import yaml
from pathlib import Path


def load_config() -> dict:
    """加载配置文件"""
    config_path = Path(__file__).parent.parent / "config" / "settings.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class DocClassifyAgent:
    """单据分类 Agent"""

    def __init__(self, llm, config):
        self.llm = llm
        self.doc_types = config["documents"]["types"]

    def classify(self, content: str) -> str:
        """
        识别单据类型

        Args:
            content: 单据文本内容

        Returns:
            单据类型标签
        """
        # TODO: 实现分类逻辑
        # 提示: 设计 Prompt 让 LLM 返回单据类型
        pass


class FieldExtractAgent:
    """字段提取 Agent"""

    def __init__(self, llm, config):
        self.llm = llm
        self.fields = config["documents"]["extraction_fields"]

    def extract(self, content: str, doc_type: str) -> dict:
        """
        从单据中提取结构化字段

        Args:
            content: 单据文本内容
            doc_type: 单据类型

        Returns:
            提取的字段字典
        """
        # TODO: 实现字段提取逻辑
        # 提示: 根据 doc_type 选择字段列表，设计 Prompt 提取 JSON
        pass


class CrossValidateAgent:
    """三单校验 Agent"""

    def __init__(self, config):
        self.config = config["validation"]

    def validate(self, po: dict, delivery: dict, invoice: dict) -> dict:
        """
        三单交叉校验

        Args:
            po: 采购订单数据
            delivery: 送货单数据
            invoice: 发票数据

        Returns:
            校验结果
        """
        # TODO: 实现校验逻辑
        # 提示: 遍历校验规则，比较 PO 与送货单、发票的字段
        pass


class DocAgent:
    """主 Agent - 编排多 Agent 协作"""

    def __init__(self, config: dict):
        self.config = config
        # TODO: 初始化各 Agent
        pass

    def process_document(self, content: str, filename: str = "") -> dict:
        """
        处理单张单据

        Args:
            content: 单据文本内容
            filename: 文件名

        Returns:
            处理结果
        """
        # TODO: 实现完整处理流程
        # 1. 分类
        # 2. 提取字段
        # 3. 返回结果
        pass

    def cross_validate(self, documents: list[dict]) -> dict:
        """
        三单交叉校验

        Args:
            documents: 文档列表

        Returns:
            校验结果
        """
        # TODO: 实现三单校验
        pass

    def query(self, user_input: str) -> str:
        """
        对话式查询

        Args:
            user_input: 用户输入

        Returns:
            响应文本
        """
        # TODO: 实现查询功能
        pass
