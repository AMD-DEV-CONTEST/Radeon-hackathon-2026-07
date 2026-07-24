"""
Supply Chain DocAgent — 多 Agent 协作的供应链单据智能处理系统。
支持单据识别、信息提取、三单校验、异常处理和 ERP 录入。
"""

import yaml
from pathlib import Path
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from .rag import RAGEngine
from .tools import get_tools
from .memory import ConversationMemory
from .ui import create_ui


def load_config() -> dict:
    config_path = Path(__file__).parent.parent / "config" / "settings.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class DocClassifyAgent:
    """单据分类 Agent — 识别上传的单据类型。"""

    def __init__(self, llm, config):
        self.llm = llm
        self.doc_types = config["documents"]["types"]

    def classify(self, content: str) -> str:
        prompt = (
            f"根据以下文档内容，判断单据类型。"
            f"可选类型：{', '.join(self.doc_types)}。\n"
            f"只返回类型名称，不要其他内容。\n\n文档内容：\n{content[:2000]}"
        )
        result = self.llm.invoke(prompt)
        for doc_type in self.doc_types:
            if doc_type in result.lower():
                return doc_type
        return "unknown"


class FieldExtractAgent:
    """字段提取 Agent — 从单据中提取结构化字段。"""

    def __init__(self, llm, config):
        self.llm = llm
        self.fields = config["documents"]["extraction_fields"]

    def extract(self, content: str, doc_type: str) -> dict:
        fields = self.fields.get(doc_type, [])
        if not fields:
            return {}

        prompt = (
            f"从以下{doc_type}文档中提取以下字段，以JSON格式返回：\n"
            f"字段列表：{', '.join(fields)}\n\n"
            f"文档内容：\n{content[:3000]}\n\n"
            f"只返回JSON，格式如：{{\"{fields[0]}\": \"值\", ...}}"
        )
        result = self.llm.invoke(prompt)

        import json
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return {"raw": result}


class CrossValidateAgent:
    """三单校验 Agent — 交叉核对 PO、送货单、发票。"""

    def __init__(self, config):
        self.config = config["validation"]

    def validate(self, po: dict, delivery: dict, invoice: dict) -> dict:
        results = []
        rules = self.config["cross_check"]
        tolerance = self.config["tolerance"]

        for rule in rules:
            po_field, target_field = rule.split(":")
            po_val = po.get(po_field)
            target_val = delivery.get(target_field) or invoice.get(target_field)

            if po_val is None or target_val is None:
                results.append({"rule": rule, "status": "skip", "reason": "字段缺失"})
                continue

            # 尝试数值比较
            try:
                po_num = float(str(po_val).replace(",", ""))
                target_num = float(str(target_val).replace(",", ""))
                diff_pct = abs(po_num - target_num) / max(po_num, 1) * 100

                if "quantity" in rule and diff_pct <= tolerance["quantity_percent"]:
                    results.append({"rule": rule, "status": "pass"})
                elif "amount" in rule or "price" in rule:
                    if diff_pct <= tolerance["amount_percent"]:
                        results.append({"rule": rule, "status": "pass"})
                    else:
                        results.append({"rule": rule, "status": "fail",
                                         "diff": f"{diff_pct:.1f}%"})
                elif po_num == target_num:
                    results.append({"rule": rule, "status": "pass"})
                else:
                    results.append({"rule": rule, "status": "fail",
                                     "diff": f"{diff_pct:.1f}%"})
            except (ValueError, TypeError):
                if str(po_val).strip() == str(target_val).strip():
                    results.append({"rule": rule, "status": "pass"})
                else:
                    results.append({"rule": rule, "status": "fail"})

        all_pass = all(r["status"] in ("pass", "skip") for r in results)
        return {"all_pass": all_pass, "details": results}


class DocAgent:
    """主 Agent — 编排多 Agent 协作流程。"""

    def __init__(self, config: dict):
        self.config = config
        self.rag = RAGEngine(config)
        self.memory = ConversationMemory(config)
        self.tools = get_tools(config["tools"]["enabled"])
        self._init_llm()
        self.classify_agent = DocClassifyAgent(self.llm, config)
        self.extract_agent = FieldExtractAgent(self.llm, config)
        self.validate_agent = CrossValidateAgent(config)

    def _init_llm(self):
        from langchain_community.llms import HuggingFacePipeline
        from transformers import AutoTokenizer, AutoModelForCausalLM, pipeline
        import torch

        model_name = self.config["model"]["name"]
        device = self.config["model"]["device"]
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModelForCausalLM.from_pretrained(
            model_name, torch_dtype=torch.float16, device_map=device,
        )
        self.llm = HuggingFacePipeline(
            pipeline=pipeline(
                "text-generation", model=model, tokenizer=tokenizer,
                max_new_tokens=self.config["model"]["max_tokens"],
                temperature=self.config["model"]["temperature"],
            )
        )

    def process_document(self, content: str, filename: str = "") -> dict:
        """处理单张单据的完整流程。"""
        # 1. 分类
        doc_type = self.classify_agent.classify(content)

        # 2. 提取字段
        extracted = self.extract_agent.extract(content, doc_type)

        # 3. RAG 检索相似案例
        rag_context = self.rag.retrieve(f"{doc_type} 异常处理")

        # 4. 生成处理报告
        result = {
            "filename": filename,
            "doc_type": doc_type,
            "extracted_fields": extracted,
            "rag_context": rag_context[:500] if rag_context else "",
            "status": "extracted",
        }

        # 5. 更新记忆
        self.memory.add(
            f"处理单据: {filename} ({doc_type})",
            f"提取字段: {list(extracted.keys())}"
        )

        return result

    def cross_validate(self, documents: list[dict]) -> dict:
        """三单交叉校验。"""
        po_data = {}
        delivery_data = {}
        invoice_data = {}

        for doc in documents:
            if doc["doc_type"] == "purchase_order":
                po_data = doc["extracted_fields"]
            elif doc["doc_type"] == "delivery_note":
                delivery_data = doc["extracted_fields"]
            elif doc["doc_type"] == "invoice":
                invoice_data = doc["extracted_fields"]

        return self.validate_agent.validate(po_data, delivery_data, invoice_data)

    def query(self, user_input: str) -> str:
        """对话式查询。"""
        rag_context = self.rag.retrieve(user_input)
        enhanced = user_input
        if rag_context:
            enhanced = f"[知识库参考]\n{rag_context}\n\n[问题]\n{user_input}"

        history = self.memory.get_history()
        prompt = ChatPromptTemplate.from_messages([
            ("system", "你是供应链单据处理专家助手。基于知识库回答问题，用中文回复。"),
            MessagesPlaceholder(variable_name="history"),
            ("human", "{input}"),
        ])
        chain = prompt | self.llm
        response = chain.invoke({"input": enhanced, "history": history})
        self.memory.add(user_input, response)
        return response


def main():
    config = load_config()
    agent = DocAgent(config)
    ui = create_ui(agent)
    ui.launch(
        server_name=config["ui"]["host"],
        server_port=config["ui"]["port"],
        share=config["ui"]["share"],
    )


if __name__ == "__main__":
    main()
