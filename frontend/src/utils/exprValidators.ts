/**
 * SV 表达式语法校验（与后端 backend/app/services/core/expr_validator.py 行为对齐）。
 *
 * 配合 validateParam.ts 使用：当参数声明了 expr_type 时，优先按 expr_type 走 dispatch，
 * 而不是按参数名查 SIGNAL_PARAM_NAMES 白名单。
 */

const SV_IDENT = /^[A-Za-z_][A-Za-z0-9_]*$/

export function validateSvBooleanExpr(value: string): string | null {
  if (!value || !value.trim()) return '表达式不能为空'

  // 字符集
  if (!/^[A-Za-z0-9_!&|()=<>~+\-*\s'.]+$/.test(value)) {
    return '包含非法字符（仅允许 SV 标识符与逻辑/比较/位算子 ! && || == != < > ~ + - * 与括号）'
  }

  // 括号配对
  let depth = 0
  for (const ch of value) {
    if (ch === '(') depth++
    else if (ch === ')') {
      depth--
      if (depth < 0) return '括号不配对（出现多余的右括号）'
    }
  }
  if (depth !== 0) return '括号不配对（左右括号数量不一致）'

  // 重复算子（`&& &&` / `|| ||` / `&&&` / `|||` 等典型 LLM 错误）
  if (/&&\s*&&|\|\|\s*\|\||&&&|\|\|\|/.test(value)) {
    return '包含重复的逻辑算子'
  }

  // 至少含一个标识符
  if (!/[A-Za-z_][A-Za-z0-9_]*/.test(value)) {
    return '表达式中未发现任何信号名'
  }

  return null
}

export function validateSvIdentifierList(value: string): string | null {
  if (!value || !value.trim()) return '状态列表不能为空'

  const parts = value.split(',').map((p) => p.trim()).filter(Boolean)
  if (parts.length === 0) return '至少需要一个枚举值'
  if (parts.length < 2) return '状态列表至少需要 2 个枚举值'

  for (const p of parts) {
    if (!SV_IDENT.test(p)) {
      return `枚举值 '${p}' 不是合法 SV 标识符（字母/下划线开头，仅字母/数字/下划线）`
    }
  }
  return null
}

export function validateSvBinsExpr(value: string): string | null {
  if (!value || !value.trim()) return 'bins 表达式不能为空'

  const s = value.trim()
  if (!s.startsWith('{') || !s.endsWith('}')) {
    return '必须用 {...} 包裹'
  }
  const inner = s.slice(1, -1).trim()
  if (!inner) return '{} 内部不能为空'

  if (!/^[A-Za-z0-9_'\s,:[\]]+$/.test(inner)) {
    return '内部包含非法字符（仅允许标识符、数字、十六进制、范围 N:M、`[...]` 与逗号）'
  }

  // 中括号配对
  const open = (inner.match(/\[/g) || []).length
  const close = (inner.match(/\]/g) || []).length
  if (open !== close) return '中括号 [ ] 不配对'

  return null
}

/** expr_type → validator 的统一分发，未知 expr_type 返回 null（不校验） */
export function validateByExprType(exprType: string, value: string): string | null {
  switch (exprType) {
    case 'sv_identifier':
      return SV_IDENT.test(value)
        ? null
        : '必须是合法 SystemVerilog 标识符（字母/下划线开头，仅字母/数字/下划线）'
    case 'sv_identifier_list':
      return validateSvIdentifierList(value)
    case 'sv_boolean_expr':
      return validateSvBooleanExpr(value)
    case 'sv_bins_expr':
      return validateSvBinsExpr(value)
    case 'integer':
      return /^-?\d+$/.test(value) ? null : '必须是整数'
    case 'free_text':
      return /[\r\n\t]/.test(value) ? '不能含换行/制表符' : null
    default:
      return null  // 未知 expr_type：不校验
  }
}
