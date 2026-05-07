/**
 * 参数值前端校验（方案 3 ParametersForm 用）。
 *
 * 优先级：
 *   1. 若参数声明了 expr_type → 走 validateByExprType()（metadata-driven）
 *   2. 否则 fallback：本文件下方的 SIGNAL_PARAM_NAMES 白名单 + 数字 + 自由文本三段
 *
 * 后端在 _map_params_with_source 里也走同样逻辑（pipeline.py），前后端契约一致。
 */
import { validateByExprType } from './exprValidators'

const SV_IDENT_RE = /^[a-zA-Z_][a-zA-Z0-9_]*$/

// Fallback 白名单：当参数未声明 expr_type 时，名字在此集合内按 sv_identifier 校验
const SIGNAL_PARAM_NAMES = new Set([
  'enable', 'data', 'valid', 'ready', 'signal', 'state_sig',
  'target', 'start_event', 'end_event', 'module_name', 'group_name',
  'clk', 'rst', 'rst_n',
  // FSM 状态枚举值，在 template_body 里被拼到 property 名与状态值比较中
  'from_state', 'to_state',
])

/**
 * 返回错误消息，或 null 表示校验通过。
 *
 * @param exprType 可选：模板 YAML 声明的 expr_type；声明了就优先按这个 dispatch
 */
export function validateParamValue(
  paramName: string,
  paramType: string,
  value: string | number | string[],
  exprType?: string,
): string | null {
  // 列表类型（一般是 signals 数组）跳过校验
  if (Array.isArray(value)) return null

  const str = String(value).trim()
  if (str === '') {
    return '值不能为空'
  }

  // 优先按 expr_type dispatch（metadata-driven）
  if (exprType) {
    return validateByExprType(exprType, str)
  }

  // ↓↓↓ 以下是 fallback 路径（旧模板未声明 expr_type 时走）↓↓↓

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

  // 其他自由文本参数（state_list / bins_expr / condition 等 SV 表达式语法）：
  // 至少不允许换行/制表，避免 Jinja2 输出畸形
  if (/[\r\n\t]/.test(str)) {
    return '不能含换行/制表符'
  }
  return null
}
