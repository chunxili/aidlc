/** 后端契约类型。以 .aidlc/design/api-specification.md 为准。 */

export type Role = 'OPERATOR' | 'USER' | 'VERIFIER' | 'ADMIN'
export type Category = 'FOOD' | 'TRAVEL' | 'SHOPPING' | 'LIFE'
export type CampaignStatus = 'PENDING' | 'ACTIVE' | 'ENDED'

export interface User {
  id: number
  username: string
  display_name: string
  role: Role
}

export interface LoginResult {
  access_token: string
  token_type: string
  user: User
}

export interface Campaign {
  id: number
  name: string
  category: Category
  face_value: string
  total_stock: number
  claimed_count: number
  remaining_stock: number
  status: CampaignStatus
  start_at: string
  end_at: string
  validity_minutes: number
  per_user_limit: number
}

export interface AvailableCampaign {
  id: number
  name: string
  category: Category
  face_value: string
  remaining_stock: number
  end_at: string
  validity_minutes: number
  per_user_limit: number
  my_claimed_count: number
}

export interface Coupon {
  id: number
  code: string
  campaign_id: number
  campaign_name: string
  face_value: string
  status: 'UNUSED' | 'USED'
  /** 派生值：可用 / 已核销 / 已过期。"已过期"不落库（ADR-002） */
  display_status: '可用' | '已核销' | '已过期'
  seq: number
  claimed_at: string
  expires_at: string
}

export interface ClaimResult {
  coupon: Coupon
  risk: {
    score: number | null
    decision: string
    decided_by: string
    degraded: boolean
    reason: string | null
  }
}

export interface Paged<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface Recommendation {
  campaign_id: number
  campaign_name: string
  category: Category
  face_value: string
  remaining_stock: number
  reason: string
}

export interface RecommendationResult {
  items: Recommendation[]
  degraded: boolean
  degrade_reason: string | null
  cold_start: boolean
}

export interface RedeemCheck {
  code: string
  campaign_name: string
  face_value: string
  display_status: string
  owner: string
  redeemable: boolean
  reason: string | null
}

export interface RedeemResult {
  code: string
  face_value: string
  used_at: string
  used_by: string
}

export interface RiskEvent {
  id: number
  user_id: number
  username: string
  campaign_id: number | null
  window_request_count: number
  risk_score: number | null
  decision: 'PASS' | 'BLOCK' | 'MANUAL_REVIEW'
  decided_by: 'RULE' | 'AI'
  degraded: boolean
  /** 判定理由。运营看不到理由就无从审核（FR-052 AC-2） */
  ai_reason: string
  status: 'PENDING' | 'RELEASED' | 'KEPT'
  handled_by: string | null
  handled_at: string | null
  created_at: string
}

export interface CampaignStats {
  campaign_id: number
  campaign_name: string
  total_stock: number
  claimed_count: number
  remaining_stock: number
  used_count: number
  active_count: number
  expired_count: number
  claim_rate: number
  /** claimed_count=0 时为 null，界面显示「—」 */
  redeem_rate: number | null
  /** 口径说明由后端下发，前端不硬编码，避免口径漂移 */
  claim_rate_basis: string
  redeem_rate_basis: string
}

export interface Overview {
  campaign_count: number
  total_stock: number
  claimed_count: number
  used_count: number
  risk_blocked_24h: number
  risk_pending_count: number
}

export interface Integrity {
  inv1_stock_overflow_count: number
  inv2_mismatch_campaign_ids: number[]
  ok: boolean
}

export const CATEGORY_LABEL: Record<Category, string> = {
  FOOD: '餐饮',
  TRAVEL: '出行',
  SHOPPING: '购物',
  LIFE: '生活服务',
}

export const ROLE_LABEL: Record<Role, string> = {
  OPERATOR: '运营人员',
  USER: '普通用户',
  VERIFIER: '核销人员',
  ADMIN: '管理员',
}

/** 错误码 → 用户文案。按 code 分支（frontend-design.md 第五节） */
export const ERROR_MESSAGE: Record<string, string> = {
  OUT_OF_STOCK: '库存不足',
  PER_USER_LIMIT_REACHED: '已达领取上限',
  CAMPAIGN_NOT_ACTIVE: '活动未开始或已结束',
  COUPON_ALREADY_USED: '已核销',
  COUPON_EXPIRED: '券已过期',
  COUPON_NOT_FOUND: '券不存在',
  RISK_BLOCKED: '操作过于频繁，已被风控拦截',
  RISK_MANUAL_REVIEW: '账号存在异常，需人工审核，审核通过后请重新领取',
  STOCK_CANNOT_DECREASE: '库存只能调高',
  FORBIDDEN: '无权访问该资源',
}
