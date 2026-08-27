# -*- coding: utf-8 -*-
"""分析 qwen 生成拓扑的原始字段质量：layer/type 枚举、边引用、节点数。"""
import json
import sys
sys.path.insert(0, ".")
from app.ai.tools import generate_topology

# 模拟用户真实 CSV 提取文本（含中文列头）
asset_text = (
    "设备名称,设备类型,IP地址,网络层级,安全域\n"
    "核心交换机-01,交换机,192.168.1.1,核心层,核心区\n"
    "核心交换机-02,交换机,192.168.1.2,核心层,核心区\n"
    "汇聚交换机-01,交换机,192.168.1.3,汇聚层,核心区\n"
    "汇聚交换机-02,交换机,192.168.1.4,汇聚层,核心区\n"
    "边界防火墙-01,防火墙,192.168.1.5,汇聚层,DMZ区\n"
    "边界防火墙-02,防火墙,192.168.1.6,汇聚层,DMZ区\n"
    "应用服务器-01,服务器,192.168.1.10,接入层,服务器区\n"
    "应用服务器-02,服务器,192.168.1.11,接入层,服务器区\n"
    "数据库服务器-01,数据库,192.168.1.20,接入层,服务器区\n"
    "办公终端-01,终端,192.168.2.21,接入层,办公区\n"
    "办公终端-02,终端,192.168.2.22,接入层,办公区\n"
)

result = generate_topology(asset_text)
data = json.loads(result)
if "error" in data:
    print("!! 生成失败:", json.dumps(data, ensure_ascii=False)[:500])
    sys.exit(1)

nodes = data.get("nodes") or []
edges = data.get("edges") or []
zones = data.get("security_zones") or []
print(f"nodes={len(nodes)} edges={len(edges)} zones={len(zones)}")

# layer / type 枚举检查
layer_vals = sorted({n.get("layer") for n in nodes})
type_vals = sorted({n.get("type") for n in nodes})
print("layer 取值:", layer_vals)
print("type 取值:", type_vals)

# 边引用检查
node_ids = {n.get("id") for n in nodes}
node_labels = {n.get("label") for n in nodes}
bad_edges = [e for e in edges if e.get("source") not in node_ids or e.get("target") not in node_ids]
label_refs = [e for e in edges if e.get("source") in node_labels and e.get("target") in node_labels]
print(f"边引用节点id失败: {len(bad_edges)} 条; 用label引用: {len(label_refs)} 条")
if bad_edges:
    print("bad edge 示例:", json.dumps(bad_edges[:3], ensure_ascii=False)[:400])

# 安全域节点引用
zone_ref_ok = all(
    z and all(nid in node_ids for nid in (z.get("nodes") or [])) for z in zones
)
print("安全域节点引用全部有效:", zone_ref_ok)

print("\n--- 节点示例 ---")
for n in nodes[:3]:
    print(json.dumps(n, ensure_ascii=False))
print("\n--- 边示例 ---")
for e in edges[:3]:
    print(json.dumps(e, ensure_ascii=False))
