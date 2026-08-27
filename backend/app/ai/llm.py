"""模型层：只负责 provider -> 模型实例。

- get_deepseek()：DeepSeek-V3 文本模型实例，ChatOpenAI 接入（OpenAI 兼容协议，兼容 function calling），
  用于文本对话、招投标编写、废标检查、测评清单生成、知识问答等纯文本任务；
- get_qwen_text()：千问文本模型实例（qwen-max，DashScope OpenAI 兼容协议，支持 JSON 结构化输出），
  用于网络拓扑生成等对结构化输出质量要求高的任务；
- get_qwen_vl()：Qwen-VL 多模态模型实例，DashScope SDK 接入，用于测评截图分析任务
  （识别截图内容、提取关键信息）；
- get_embeddings()：Embedding 模型实例，用于向量化等保标准文档和历史标书，写入 Qdrant。

模型层只做实例化，不组装 Prompt、不调用链路、不碰记忆。
API Key 从环境变量读取（DEEPSEEK_API_KEY / DASHSCOPE_API_KEY），temperature 等参数集中配置。
"""

from functools import lru_cache

from langchain_openai import ChatOpenAI

from ..config import settings
from ..exceptions import BusinessError, ErrorCode
from ..log import get_logger

logger = get_logger("llm")

# DeepSeek OpenAI 兼容端点（ChatOpenAI.base_url）
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
# DashScope OpenAI 兼容端点（千问文本模型，ChatOpenAI.base_url）
QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def _require_api_key(key: str, env_name: str) -> str:
    """API Key 缺失时抛出业务异常，提示补配置（避免静默带空 Key 调用）。"""
    if not key or not key.strip():
        raise BusinessError(ErrorCode.VALIDATION, f"缺少 {env_name} 配置，请在环境文件中填写后重启服务")
    return key.strip()


@lru_cache(maxsize=1)
def get_deepseek() -> ChatOpenAI:
    """DeepSeek-V3 文本模型实例（deepseek-chat，OpenAI 兼容协议，支持 function calling）。"""
    return ChatOpenAI(
        model="deepseek-chat",
        base_url=DEEPSEEK_BASE_URL,
        api_key=_require_api_key(settings.deepseek_api_key, "DEEPSEEK_API_KEY"),
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
    )


@lru_cache(maxsize=1)
def get_qwen_text() -> ChatOpenAI:
    """千问文本模型实例（qwen-max，DashScope OpenAI 兼容协议，支持 JSON 结构化输出）。

    用于网络拓扑生成等结构化输出任务：JSON 模式稳定、节点/边/安全域结构完整；
    温度调低、token 上限放宽，避免拓扑 JSON 被截断。
    """
    return ChatOpenAI(
        model="qwen3.7-flash",
        base_url=QWEN_BASE_URL,
        api_key=_require_api_key(settings.dashscope_api_key, "DASHSCOPE_API_KEY"),
        temperature=0.2,
        max_tokens=4096,
    )


class QwenVLModel:
    """Qwen-VL 多模态模型实例：封装 DashScope MultiModalConversation。

    调用方式：
        model = get_qwen_vl()
        text = model.invoke([{"role": "user", "content": [
            {"image": "https://.../截图.png"}, {"text": "识别图中的配置信息"}]}])
    """

    def __init__(self, api_key: str, model: str | None = None):
        self.api_key = api_key
        self.model = model or settings.vlm_model

    def invoke(self, messages: list[dict]) -> str:
        """调用多模态对话，返回模型输出的纯文本。"""
        import dashscope

        response = dashscope.MultiModalConversation.call(
            api_key=self.api_key,
            model=self.model,
            messages=messages,
        )
        if response.status_code != 200:
            logger.error("Qwen-VL 调用失败 code=%s message=%s", response.status_code, response.message)
            raise BusinessError(ErrorCode.INTERNAL, "VLM 截图识别服务调用失败")
        # DashScope 多模态响应 content 为列表，取其中 text 片段拼接
        content = response.output.choices[0].message.content
        if isinstance(content, list):
            return "".join(
                part.get("text", "") for part in content if isinstance(part, dict) and part.get("text")
            )
        return str(content)


@lru_cache(maxsize=1)
def get_qwen_vl() -> QwenVLModel:
    """Qwen-VL 多模态模型实例（DashScope SDK 接入）。"""
    return QwenVLModel(api_key=_require_api_key(settings.dashscope_api_key, "DASHSCOPE_API_KEY"))


class DashScopeEmbeddings:
    """Embedding 模型实例：封装 DashScope TextEmbedding。

    调用方式：
        embeddings = get_embeddings()
        vector = embeddings.embed("文本")            # 单条 -> list[float]
        vectors = embeddings.embed_documents([...])  # 批量
        vector_q = embeddings.embed_query("查询")    # 检索查询向量
    """

    def __init__(self, api_key: str, model: str | None = None):
        self.api_key = api_key
        self.model = model or settings.embedding_model

    @staticmethod
    def _parse(response) -> list[list[float]]:
        if response.status_code != 200:
            raise BusinessError(ErrorCode.INTERNAL, "Embedding 服务调用失败")
        return [item["embedding"] for item in response.output["embeddings"]]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """批量向量化（文档侧，写入 Qdrant 用）。"""
        import dashscope

        response = dashscope.TextEmbedding.call(
            api_key=self.api_key, model=self.model, input=texts, text_type="document"
        )
        return self._parse(response)

    def embed_query(self, text: str) -> list[float]:
        """单条查询向量（检索侧）。"""
        import dashscope

        response = dashscope.TextEmbedding.call(
            api_key=self.api_key, model=self.model, input=[text], text_type="query"
        )
        return self._parse(response)[0]

    def embed(self, text: str) -> list[float]:
        """单条向量化（语义上与 embed_query 一致，检索场景使用）。"""
        return self.embed_query(text)


@lru_cache(maxsize=1)
def get_embeddings() -> DashScopeEmbeddings:
    """Embedding 模型实例（DashScope text-embedding-v3，用于向量化入库与检索）。"""
    return DashScopeEmbeddings(api_key=_require_api_key(settings.dashscope_api_key, "DASHSCOPE_API_KEY"))
