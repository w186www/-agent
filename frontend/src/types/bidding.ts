export interface Step {
  id: number
  label: string
  status: 'done' | 'active' | 'pending'
}

export interface CheckItem {
  id: number
  text: string
  status: 'pass' | 'warn' | 'fail'
}
