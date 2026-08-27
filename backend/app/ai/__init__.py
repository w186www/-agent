"""AI 三层架构：模型层 / 提示词层 / 记忆层。

- llm.py         模型层：provider -> 模型实例（get_deepseek / get_qwen_vl / get_embeddings）
- prompt_layer.py 提示词层：Prompt 定义 + Chain 组装（get_xxx_prompt / build_chain）
- memory.py      记忆层：历史记忆构建 + RAG 检索增强（get_session_memory / get_rag_context 等）

协作关系：请求进来 -> 记忆层构建历史与检索片段 -> 提示词层选择 Prompt 并组装 Chain
          -> 模型层提供模型实例 -> Chain.invoke() 输出结果。
"""
