import { apiClient } from './client'

export interface ScenarioParam { name: string; description: string; required: boolean }
export interface Scenario { id: string; name: string; description: string; params: ScenarioParam[]; template: string }

export const intentBuilderApi = {
  scenarios: async (code_type: string) => {
    const res = await apiClient.get<{ code_type: string; scenarios: Scenario[] }>('/intent-builder/scenarios', { params: { code_type } })
    return res.data
  },
  build: async (code_type: string, scenario_type: string, params: Record<string, string>) => {
    const res = await apiClient.post<{ intent_text: string }>('/intent-builder/build', { code_type, scenario_type, params })
    return res.data
  },
}
