export interface CheckPoint {
  id: string
  label: string
  code: string
  active?: boolean
}

export interface ResultItem {
  id: string
  label: string
  value: string
  status?: 'ok' | 'warn'
}
