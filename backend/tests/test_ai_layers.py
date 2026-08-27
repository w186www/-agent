"""AI 三层架构测试：模型层 / 提示词层 / 记忆层。

- 模型层：API Key 缺失时 get_xxx() 抛出业务异常，工厂不进行网络调用；
- 提示词层：各 Prompt 模板变量齐全、链路可组装；
- 记忆层：会话历史窗口构建、RAG 检索合并排序、招投标/测评专用上下文。
"""

import time

import pytest
from langchain_core.runnables import Runnable

from app.ai import memory as memory_module
from app.ai import prompt_layer
from app.ai.llm import DashScopeEmbeddings, QwenVLModel, get_deepseek, get_embeddings, get_qwen_vl
from app.ai.memory import (
    build_memory_prompt,
    format_retrieved_chunks,
    get_assessment_context,
    get_bidding_context,
    get_rag_context,
    get_session_memory,
    qdrant_collection_of,
    search_similar_chunks,
    should_retrieve,
)
from app.config import settings
from app.db.models import ChatMessage, ChatSession, KbChunk, KbDocument
from app.exceptions import BusinessError

# ---------------------------------------------------------------------------
# 模型层
# ---------------------------------------------------------------------------


def test_deepseek_requires_api_key():
    """未配置 DEEPSEEK_API_KEY 时应抛出业务异常，避免静默带空 Key。

    本地开发已配置真实 Key 时跳过（Key 存在时工厂应正常返回实例）。
    """
    if settings.deepseek_api_key:
        pytest.skip("已配置 DEEPSEEK_API_KEY，跳过缺 Key 场景")
    with pytest.raises(BusinessError, match="DEEPSEEK_API_KEY"):
        get_deepseek()


def test_qwen_vl_requires_api_key(monkeypatch):
    """缺 DASHSCOPE_API_KEY 时创建多模态模型实例应抛业务异常。"""
    monkeypatch.setattr(settings, "dashscope_api_key", "")
    with pytest.raises(BusinessError, match="DASHSCOPE_API_KEY"):
        get_qwen_vl()


def test_embeddings_requires_api_key(monkeypatch):
    """缺 DASHSCOPE_API_KEY 时创建 Embedding 实例应抛业务异常。"""
    monkeypatch.setattr(settings, "dashscope_api_key", "")
    with pytest.raises(BusinessError, match="DASHSCOPE_API_KEY"):
        get_embeddings()


def test_qwen_vl_and_embeddings_instances():
    """直接实例化封装类（绕过工厂）不应触发网络调用。"""
    model = QwenVLModel(api_key="test-key")
    assert model.model == "qwen-vl-plus"
    emb = DashScopeEmbeddings(api_key="test-key")
    assert emb.model == "text-embedding-v3"


# ---------------------------------------------------------------------------
# 记忆层：历史记忆
# ---------------------------------------------------------------------------


def _make_session(client, db, uid: int, now: int) -> int:
    session = ChatSession(
        user_id=uid, role_type=0, intent_type=0, title="会话", created_at=now, updated_at=now
    )
    db.add(session)
    db.commit()
    return session.id


def _add_messages(db, uid: int, sid: int, now: int, texts: list[str]):
    for i, text in enumerate(texts):
        db.add(ChatMessage(
            user_id=uid, session_id=sid, role=i % 2, request_id=f"m{i}",
            content=text, created_at=now + i,
        ))
    db.commit()


def test_session_memory_window(client, db_session):
    """历史消息按 created_at 升序构建记忆，窗口保留最近 k 轮。"""
    token, uid = _register_and_login(client)
    now = int(time.time())
    sid = _make_session(client, db_session, uid, now)
    _add_messages(db_session, uid, sid, now, ["h0", "a0", "h1", "a1", "h2", "a2"])

    memory = get_session_memory(sid, k=2, db=db_session)
    history = memory.load_memory_variables({})["history"]
    assert "h0" not in history      # 窗口已截断早期消息
    assert "h2" in history and "a2" in history
    # role=0 的 Human 与 role=1 的 AI 均按顺序进入记忆
    assert history.index("h2") < history.index("a2")


def test_build_memory_prompt(client, db_session):
    """历史记忆与 RAG 检索结果组装为 Prompt 变量。"""
    token, uid = _register_and_login(client)
    now = int(time.time())
    sid = _make_session(client, db_session, uid, now)
    _add_messages(db_session, uid, sid, now, ["你好", "你好，我是等保测评助手"])

    memory = get_session_memory(sid, db=db_session)
    variables = build_memory_prompt(memory, rag_context="【等保标准库】控制点要求...")
    assert "你好" in variables["history"]
    assert "等保标准库" in variables["rag_context"]
    assert "history" in variables and "rag_context" in variables


# ---------------------------------------------------------------------------
# 记忆层：RAG 检索增强（mock Qdrant 与 Embedding）
# ---------------------------------------------------------------------------


class FakeHit:
    """假 Qdrant 命中：id 为向量点 ID（与 kb_chunks.vector_id 关联），payload 不存原文。"""

    def __init__(self, score: float, payload: dict, id: str = ""):
        self.score = score
        self.payload = payload
        self.id = id


class FakeQdrantClient:
    """假 Qdrant 客户端：模拟新版 qdrant-client（>=1.14，query_points 返回 .points）。"""

    def __init__(self, hits: dict):
        self.hits = hits

    def collection_exists(self, name: str) -> bool:
        return name in self.hits

    def query_points(self, collection_name: str, query, query_filter=None, limit: int | None = None):
        from types import SimpleNamespace
        return SimpleNamespace(points=self.hits.get(collection_name, [])[:limit])


class FakeEmbeddings:
    def embed(self, text: str) -> list[float]:
        return [1.0, 0.0]


def _patch_rag(monkeypatch, hits: dict):
    monkeypatch.setattr(memory_module, "get_qdrant_client", lambda: FakeQdrantClient(hits))
    monkeypatch.setattr(memory_module, "get_embeddings", lambda: FakeEmbeddings())


def test_qdrant_collection_mapping():
    assert qdrant_collection_of(0) == "dengbao_kb_0"
    assert qdrant_collection_of(1) == "dengbao_kb_1"
    assert qdrant_collection_of(2) == "dengbao_kb_2"


def test_get_rag_context_merge_sort(monkeypatch, db_session):
    """跨 collection 并行检索，合并后按相似度降序取 top-k；原文回查 MySQL kb_chunks。"""
    hits = {
        "dengbao_kb_0": [FakeHit(0.8, {"doc_id": 1, "chunk_index": 0}, id="v-a0")],
        "dengbao_kb_1": [
            FakeHit(0.9, {"doc_id": 2, "chunk_index": 1}, id="v-b1"),
            FakeHit(0.7, {"doc_id": 3, "chunk_index": 0}, id="v-b2"),
        ],
    }
    _patch_rag(monkeypatch, hits)
    db_session.add_all([
        KbChunk(doc_id=1, vector_id="v-a0", chunk_index=0, content="标准A", char_count=3),
        KbChunk(doc_id=2, vector_id="v-b1", chunk_index=1, content="企标B", char_count=3),
        KbChunk(doc_id=3, vector_id="v-b2", chunk_index=0, content="企标C", char_count=3),
    ])
    db_session.commit()
    result = get_rag_context("身份鉴别要求", [0, 1], top_k=2, db=db_session)
    assert [s["text"] for s in result] == ["企标B", "标准A"]  # 按 score 降序
    assert result[0]["kb_type"] == 1 and result[1]["kb_type"] == 0


def test_get_rag_context_drops_missing_text(monkeypatch, db_session):
    """Qdrant 命中但 MySQL 无对应原文（脏数据）时，该条降级丢弃。"""
    hits = {
        "dengbao_kb_0": [
            FakeHit(0.9, {"doc_id": 1, "chunk_index": 0}, id="v-orphan"),
            FakeHit(0.5, {"doc_id": 2, "chunk_index": 0}, id="v-ok"),
        ],
    }
    _patch_rag(monkeypatch, hits)
    db_session.add(KbChunk(doc_id=2, vector_id="v-ok", chunk_index=0, content="有原文", char_count=3))
    db_session.commit()
    result = get_rag_context("查询", [0], top_k=5, db=db_session)
    assert [s["vector_id"] for s in result] == ["v-ok"]  # 无原文的 v-orphan 被丢弃


def test_get_bidding_context(monkeypatch, db_session):
    """招投标专用检索：返回参考段落与引用 doc_id 列表。"""
    hits = {
        "dengbao_kb_2": [
            FakeHit(0.9, {"doc_id": 10, "chunk_index": 0}, id="v-t1"),
            FakeHit(0.6, {"doc_id": 11, "chunk_index": 2}, id="v-t2"),
        ],
    }
    _patch_rag(monkeypatch, hits)
    db_session.add_all([
        KbChunk(doc_id=10, vector_id="v-t1", chunk_index=0, content="历史标书：商务部分结构", char_count=10),
        KbChunk(doc_id=11, vector_id="v-t2", chunk_index=2, content="历史标书：技术方案", char_count=8),
    ])
    db_session.commit()
    ctx = get_bidding_context("XX项目招标", db=db_session)
    assert "历史标书 10" in ctx["context"] and "历史标书 11" in ctx["context"]
    assert ctx["reference_doc_ids"] == [10, 11]


def test_get_assessment_context(monkeypatch, db_session):
    """测评核查专用检索：标准库 + 企业库合并，补充文档标题为 kb_references。"""
    hits = {
        "dengbao_kb_0": [FakeHit(0.85, {"doc_id": 1, "chunk_index": 0}, id="v-a1")],
        "dengbao_kb_1": [FakeHit(0.75, {"doc_id": 2, "chunk_index": 1}, id="v-a2")],
    }
    _patch_rag(monkeypatch, hits)
    db_session.add_all([
        KbDocument(kb_type=0, doc_title="GB/T 22239-2019", doc_source="等保标准", file_path="s3://a"),
        KbDocument(kb_type=1, doc_title="企业安全制度", doc_source="企标", file_path="s3://b"),
        KbChunk(doc_id=1, vector_id="v-a1", chunk_index=0, content="8.1.4.1 身份鉴别标准要求", char_count=15),
        KbChunk(doc_id=2, vector_id="v-a2", chunk_index=1, content="特殊情况说明", char_count=6),
    ])
    db_session.commit()

    refs = get_assessment_context("8.1.4.1", "身份鉴别", db=db_session)
    assert len(refs) == 2
    by_doc = {r["doc_id"]: r for r in refs}
    assert by_doc[1]["doc_title"] == "GB/T 22239-2019"
    assert by_doc[2]["doc_title"] == "企业安全制度"
    assert by_doc[1]["kb_type"] == 0 and by_doc[2]["kb_type"] == 1
    assert by_doc[1]["similarity"] == 0.85
    assert "标准要求" in by_doc[1]["chunk"]


def test_should_retrieve():
    """轻量意图判断：空/极短/确认语/礼貌语/推进语不检索，正常问题触发检索。"""
    assert not should_retrieve("")
    assert not should_retrieve("嗯")
    assert not should_retrieve("好的")
    assert not should_retrieve("谢谢")
    assert not should_retrieve("继续")
    assert not should_retrieve("请继续分析")
    assert should_retrieve("身份鉴别的测评要求是什么？")


def test_format_retrieved_chunks():
    """注入文本结构：【参考资料】+【用户问题】。"""
    chunks = [
        {"chunk_id": 1, "text": "标准片段A"},
        {"chunk_id": 2, "text": "标准片段B"},
    ]
    text = format_retrieved_chunks(chunks)
    assert text.startswith("【参考资料】")
    assert "标准片段A" in text and "标准片段B" in text
    assert text.endswith("【用户问题】")
    assert format_retrieved_chunks([]) == ""


def test_search_similar_chunks(monkeypatch, db_session):
    """知识问答检索：补 file_name，返回完整来源结构。"""
    doc1 = KbDocument(kb_type=0, doc_title="GB/T 22239-2019", file_path="s3://std/22239.pdf", chunk_count=0)
    doc2 = KbDocument(kb_type=1, doc_title="企业制度", user_id=1, file_path="s3://u1/doc.docx", chunk_count=0)
    db_session.add_all([doc1, doc2])
    db_session.commit()
    hits = {
        "dengbao_kb_0": [FakeHit(0.8, {"doc_id": doc1.id, "chunk_index": 0}, id="v-qa0")],
        "dengbao_kb_1": [FakeHit(0.7, {"doc_id": doc2.id, "chunk_index": 1}, id="v-qa1")],
    }
    _patch_rag(monkeypatch, hits)
    chunk1 = KbChunk(doc_id=doc1.id, vector_id="v-qa0", chunk_index=0, content="标准片段", char_count=4)
    chunk2 = KbChunk(doc_id=doc2.id, vector_id="v-qa1", chunk_index=1, content="企业片段", char_count=4)
    db_session.add_all([chunk1, chunk2])
    db_session.commit()
    result = search_similar_chunks("身份鉴别要求", user_id=1, db=db_session, top_k=3)
    by_id = {s["chunk_id"]: s for s in result}
    assert set(by_id) == {chunk1.id, chunk2.id}
    assert by_id[chunk1.id]["file_name"] == "22239.pdf"
    assert by_id[chunk2.id]["file_name"] == "doc.docx"
    assert by_id[chunk1.id]["resource_id"] == doc1.id
    assert by_id[chunk2.id]["resource_id"] == doc2.id
    assert "标准片段" in by_id[chunk1.id]["text"] and by_id[chunk1.id]["score"] == 0.8


# ---------------------------------------------------------------------------
# 提示词层
# ---------------------------------------------------------------------------


def test_prompt_templates_variables():
    """各 Prompt 模板的输入变量符合约定。"""
    assert set(prompt_layer.get_router_prompt().input_variables) == {"role_type", "input"}
    assert set(prompt_layer.get_bidding_prompt().input_variables) == {"history", "rag_context", "input"}
    assert set(prompt_layer.get_assessment_prompt().input_variables) == {
        "checklist_code", "checklist_name", "vlm_analysis", "human_record", "kb_references", "input",
    }
    assert set(prompt_layer.get_knowledge_prompt().input_variables) == {"history", "rag_context", "input"}
    assert set(prompt_layer.get_compliance_prompt().input_variables) == {"tender_rules", "bidding_content"}
    # VLM 模板：控制点名称在定义时注入，运行时只需提供截图
    vlm = prompt_layer.get_vlm_prompt("8.1.4.1 身份鉴别")
    assert "身份鉴别" in repr(vlm)
    assert set(vlm.input_variables) == {"image"}


def test_build_chain_returns_runnable():
    """build_chain 返回可执行 Chain，可绑定工具列表。"""
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(model="deepseek-chat", api_key="test-key")
    prompt = prompt_layer.get_knowledge_prompt()
    chain = prompt_layer.build_chain(llm, prompt)
    assert isinstance(chain, Runnable)

    # 绑定工具：搜索/解析/截图分析
    tools = [
        {"type": "function", "function": {"name": "search_tender", "description": "搜索招标公告"}},
        {"type": "function", "function": {"name": "parse_tender", "description": "解析招标文件"}},
        {"type": "function", "function": {"name": "analyze_screenshot", "description": "分析测评截图"}},
    ]
    chain_with_tools = prompt_layer.build_chain(llm, prompt, tools=tools)
    assert isinstance(chain_with_tools, Runnable)


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _register_and_login(client, username: str = "ai_user", password: str = "secret123") -> tuple[str, int]:
    resp = client.post("/auth/register", json={"username": username, "password": password})
    assert resp.status_code == 201, resp.text
    resp = client.post("/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    return data["access_token"], data["user"]["id"]
