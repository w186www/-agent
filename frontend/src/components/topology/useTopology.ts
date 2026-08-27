/**
 * 拓扑图数据转换与自动布局 composable。
 *
 * - 将后端 topology_data（原始 JSON）转换为 Vue Flow 支持的 nodes / edges；
 * - 按 layer 字段分层布局（核心层顶部 → 汇聚层中间 → 接入层底部），同层均匀分布；
 * - 按 security_zones 计算安全域虚线框包围盒。
 */

import { computed, ref, watch, type Ref } from 'vue'
import type { Node, Edge } from '@vue-flow/core'
import type { TopologyData } from '@/types/topology'

/** 安全域分组（含计算出的包围盒） */
export interface SecurityZoneGroup {
  id: string
  label: string
  description: string
  risk_level?: string
  bounds: { x: number; y: number; width: number; height: number }
}

/** 网络层级背景带（核心层/汇聚层/接入层），画布按层渲染浅色横带 */
export interface LayerBand {
  layer: string
  label: string
  bounds: { x: number; y: number; width: number; height: number }
}

// 标准三层架构布局参数：核心层（顶部）→ 汇聚层（中间）→ 接入层（底部）
const LAYER_BASE_Y: Record<string, number> = {
  core: 80,
  aggregation: 260,
  access: 440,
}
const LAYER_ORDER = ['core', 'aggregation', 'access']
// 每层节点过多时换行排布，避免画布横向过长
const MAX_PER_ROW = 5
const ROW_GAP_Y = 150
const NODE_SPACING_X = 220
const START_X = 120
const NODE_WIDTH = 180
const NODE_HEIGHT = 64

export function useTopology(rawData: Ref<TopologyData | null>) {
  const nodes = ref<Node[]>([])
  const edges = ref<Edge[]>([])
  const zones = ref<SecurityZoneGroup[]>([])
  const layerBands = ref<LayerBand[]>([])

  watch(
    rawData,
    (data) => {
      if (!data) return
      const rawNodes = Array.isArray(data.nodes) ? data.nodes : []

      // 1. 节点按 layer 分组（未知层级归入 access），同层内横向均匀分布
      const layerGroups: Record<string, typeof rawNodes> = {}
      for (const node of rawNodes) {
        const layer = LAYER_ORDER.includes(node.layer) ? node.layer : 'access'
        ;(layerGroups[layer] ??= []).push(node)
      }
      // 保证 core -> aggregation -> access 顺序稳定
      const positionedNodes: Node[] = []
      for (const layer of LAYER_ORDER) {
        const group = layerGroups[layer]
        if (!group) continue
        const baseY = LAYER_BASE_Y[layer] ?? 440
        group.forEach((node, index) => {
          // 同层节点每行最多 MAX_PER_ROW 个，超出换行到该层下一行
          const row = Math.floor(index / MAX_PER_ROW)
          const col = index % MAX_PER_ROW
          positionedNodes.push({
            id: node.id,
            type: 'topology-node',
            position: { x: START_X + col * NODE_SPACING_X, y: baseY + row * ROW_GAP_Y },
            data: {
              label: node.label,
              deviceType: node.type,
              ip: node.ip,
              mac: node.mac,
              layer: node.layer || 'access',
              zone: node.zone,
              deviceModel: node.device_model,
              description: node.description,
            },
          })
        })
      }
      nodes.value = positionedNodes

      // 2. 边转换（Edge 为递归泛型联合，直接标注会触发 TS 深度实例化，改用 any 中转）
      const nodeLayerById = new Map<string, string>()
      for (const n of positionedNodes) nodeLayerById.set(n.id, String(n.data.layer || ''))
      const edgeList: any[] = []
      for (const edge of Array.isArray(data.edges) ? data.edges : []) {
        edgeList.push({
          id: edge.id,
          source: edge.source,
          target: edge.target,
          type: 'topology-edge',
          label: edge.label,
          animated: true,
          data: {
            bandwidth: edge.bandwidth,
            sourceLayer: nodeLayerById.get(edge.source) || '',
            targetLayer: nodeLayerById.get(edge.target) || '',
          },
        })
      }
      edges.value = edgeList

      // 3. 安全域分组（计算包围盒）
      zones.value = (Array.isArray(data.security_zones) ? data.security_zones : [])
        .map((zone): SecurityZoneGroup | null => {
          const ids = Array.isArray(zone.nodes) ? zone.nodes : []
          const zoneNodes = positionedNodes.filter((n) => ids.includes(n.id))
          if (zoneNodes.length === 0) return null
          const xs = zoneNodes.map((n) => n.position.x)
          const ys = zoneNodes.map((n) => n.position.y)
          const minX = Math.min(...xs) - 20
          const maxX = Math.max(...xs) + NODE_WIDTH + 20
          const minY = Math.min(...ys) - 34
          const maxY = Math.max(...ys) + NODE_HEIGHT + 24
          return {
            id: zone.zone_name,
            label: zone.zone_name,
            description: zone.description,
            risk_level: zone.risk_level,
            bounds: { x: minX, y: minY, width: maxX - minX, height: maxY - minY },
          }
        })
        .filter((z): z is SecurityZoneGroup => z !== null)

      // 4. 网络层级背景带：按 layer 计算每层节点包围盒，供画布渲染层背景
      const layerLabels: Record<string, string> = {
        core: '核心层',
        aggregation: '汇聚层',
        access: '接入层',
      }
      const bands: LayerBand[] = []
      for (const layer of LAYER_ORDER) {
        const groupNodes = positionedNodes.filter((n) => n.data.layer === layer)
        if (groupNodes.length === 0) continue
        const xs = groupNodes.map((n) => n.position.x)
        const ys = groupNodes.map((n) => n.position.y)
        const minX = Math.min(...xs) - 40
        const maxX = Math.max(...xs) + NODE_WIDTH + 40
        const minY = Math.min(...ys) - 50
        const maxY = Math.max(...ys) + NODE_HEIGHT + 40
        bands.push({
          layer,
          label: layerLabels[layer] || layer,
          bounds: { x: minX, y: minY, width: maxX - minX, height: maxY - minY },
        })
      }
      layerBands.value = bands
    },
    { immediate: true },
  )

  return {
    nodes,
    edges,
    zones,
    layerBands,
    summary: computed(() => rawData.value?.summary || ''),
  }
}
