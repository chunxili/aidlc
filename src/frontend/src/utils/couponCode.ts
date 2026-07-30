/**
 * 券码字符规则与扫码文本解析。
 *
 * 字符集刻意不含 0 O 1 I L U，与后端生成规则一致：这些字符人眼易混淆，
 * 门店口述或手工补录时最容易出错。
 */

export const CODE_LENGTH = 10

const CHARS = '23456789ABCDEFGHJKMNPQRSTVWXYZ'

/** 手工输入时过滤非法字符 */
export const CODE_CLEAN_RE = new RegExp(`[^${CHARS}]`, 'g')

const EXACT_RE = new RegExp(`^[${CHARS}]{${CODE_LENGTH}}$`)
const SEPARATOR_RE = new RegExp(`[^${CHARS}]+`)

/** 归一化后校验，通过则返回券码，否则 null */
function normalize(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const v = value.trim().toUpperCase()
  return EXACT_RE.test(v) ? v : null
}

/** 从任意字符串里挑出唯一一个长度合法的券码候选 */
function pickToken(text: string): string | null {
  const hits = text.split(SEPARATOR_RE).filter((t) => t.length === CODE_LENGTH)
  // 出现多个候选说明无法判定是哪个，宁可让核销员手工确认，也不要猜错核销对象
  return hits.length === 1 ? hits[0] : null
}

/** 大小写无关地取字段值，二维码由谁生成的都能吃下 */
function field(obj: Record<string, unknown>, name: string): unknown {
  const key = Object.keys(obj).find((k) => k.toLowerCase() === name)
  return key === undefined ? undefined : obj[key]
}

/**
 * 解析扫码得到的原始文本，返回券码；无法识别则返回 null。
 *
 * 兼容三种载荷，避免二维码内容格式一变前端就得改：
 *   1. 纯券码            ABCD234567
 *   2. 带 code 参数的链接 https://host/verify?code=ABCD234567
 *   3. 带 code 字段的 JSON {"code":"ABCD234567"}
 */
export function extractCouponCode(raw: string): string | null {
  const text = raw.trim()
  if (!text) return null

  const exact = normalize(text)
  if (exact) return exact

  // 链接形式：优先取 code 查询参数，比在整串里瞎猜更可靠
  if (/^https?:\/\//i.test(text)) {
    try {
      const params = new URL(text).searchParams
      for (const [k, v] of params) {
        if (k.toLowerCase() === 'code') {
          const hit = normalize(v)
          if (hit) return hit
        }
      }
    } catch {
      /* 不是合法 URL，落到下面的兜底解析 */
    }
  }

  if (text.startsWith('{')) {
    try {
      const obj = JSON.parse(text) as unknown
      if (obj && typeof obj === 'object') {
        const hit = normalize(field(obj as Record<string, unknown>, 'code'))
        if (hit) return hit
      }
    } catch {
      /* 不是合法 JSON，落到下面的兜底解析 */
    }
  }

  return pickToken(text.toUpperCase())
}
