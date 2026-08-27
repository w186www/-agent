/** 网络拓扑图数据结构（与后端 generate_topology 工具输出对齐） */

export interface TopologyNodeData {
  id: string
  label: string
  /** switch / router / firewall / server / database */
  type: string
  ip: string
  mac?: string
  /** core（核心层）/ aggregation（汇聚层）/ access（接入层） */
  layer: string
  /** 所属安全域，如 "DMZ区" / "内网区" */
  zone: string
  device_model?: string
  description?: string
}

export interface TopologyEdgeData {
  id: string
  source: string
  target: string
  label: string
  bandwidth?: string
}

export interface SecurityZoneData {
  zone_name: string
  nodes: string[]
  description: string
  risk_level?: string
}

export interface TopologyData {
  nodes: TopologyNodeData[]
  edges: TopologyEdgeData[]
  security_zones: SecurityZoneData[]
  summary: string
}

/** 设备基础信息（静态拓扑原型 /topology 用） */
export interface Device {
  name: string
  type: string
  zone: string
  status: 'online' | 'warning' | 'offline'
}

/** 安全域页签（静态拓扑原型 /topology 用） */
export interface Zone {
  id: string
  label: string
  devices: number
}
