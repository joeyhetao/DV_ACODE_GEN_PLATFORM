/**
 * 参数值前端校验（方案 3 ParametersForm 用）。
 *
 * 仅做基础语法校验，避免显然错误的输入。后端 Jinja2 渲染本身不会因非法标识符崩，
 * 只是生成的 SystemVerilog 可能编译失败 — 用户自己的责任。
 */

const SV_IDENT_RE = /^[a-zA-Z_][a-zA-Z0-9_]*$/

// 这些参数名期望填 SV 标识符（信号名 / 模块名）
const SIGNAL_PARAM_NAMES = new Set([
  'enable', 'data', 'valid', 'ready', 'signal', 'state_sig',
  'target', 'start_event', 'end_event', 'module_name', 'group_name',
  'clk', 'rst', 'rst_n',
])

/**
 * 返回错误消息，或 null 表示校验通过。
 */
export function validateParamValue(
  paramName: string,
  paramType: string,
  value: string | number | string[],
): string | null {
  // 列表类型（一般是 signals 数组）跳过校验
  if (Array.isArray(value)) return null

  const str = String(value).trim()
  if (str === '') {
    return '值不能为空'
  }

  // 数字类型（max_cycles / max_delay / settle_cycles / signal_width 等）
  if (paramType === 'integer' || paramType === 'number') {
    if (!/^-?\d+$/.test(str)) {
      return '必须是整数'
    }
    return null
  }

  // 信号 / 模块名类参数：必须符合 SV 标识符
  if (SIGNAL_PARAM_NAMES.has(paramName)) {
    if (!SV_IDENT_RE.test(str)) {
      return '必须是合法 SystemVerilog 标识符（字母/下划线开头，仅字母/数字/下划线）'
    }
    return null
  }

  // 其他自由文本参数（state_list / bins_expr / from_state / condition 等）：
  // 至少不允许换行/制表，避免 Jinja2 输出畸形
  if (/[\r\n\t]/.test(str)) {
    return '不能含换行/制表符'
  }
  return null
}
