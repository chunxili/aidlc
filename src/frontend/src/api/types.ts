/** 后端契约类型。以 .aidlc/design/api-specification.md 为准。 */

export type Role = 'OPERATOR' | 'USER' | 'VERIFIER' | 'ADMIN'
export type RegisterRole = 'USER' | 'VERIFIER' | 'OPERATOR'
export type Category = 'FOOD' | 'TRAVEL' | 'SHOPPING' | 'LIFE'
export type CampaignStatus = 'PENDING' | 'ACTIVE' | 'ENDED'
export type CouponType = 'CASH' | 'DISCOUNT'
export type AccountStatus = 'ACTIVE' | 'PENDING' | 'REJECTED'

export interface Store {
  id: number
  code: string
  name: string
  district: string
  address: string
}

export interface User {
  id: number
  username: string
  display_name: string
  role: Role
  status: AccountStatus
  phone: string | null
  store_id: number | null
  store_name: string | null
  reject_reason: string | null
}

export interface LoginResult {
  access_token: string
  token_type: string
  user: User
}

export interface RegisterResult {
  user: User
  needs_approval: boolean
}

export interface PendingUser {
  id: number
  username: string
  display_name: string
  role: Role
  phone: string | null
  store_id: number | null
  store_name: string | null
  store_district: string | null
  created_at: string
}

export interface Verifier {
  id: number
  username: string
  display_name: string
  phone: string | null
  status: AccountStatus
  store_id: number
  store_code: string
  store_name: string
  store_district: string
  redeemed_count: number
  created_at: string
}

/** 运营人员名册行（FR-069）。列的是投放业绩，不是账号资料 */
export interface Operator {
  id: number
  username: string
  display_name: string
  phone: string | null
  status: AccountStatus
  campaign_count: number
  total_stock: number
  claimed_count: number
  used_count: number
  /** 分母为 0 时为 null：无人领取与领了没人用是两回事，用 0 表示前者会误导复盘 */
  redeem_rate: number | null
  created_at: string
}

export interface VerifierBrief {
  id: number
  username: string
  display_name: string
  phone: string | null
  store_name: string
  store_district: string
}

/** 核销记录行（FR-070）。金额取核销时落库的快照，非活动现值重算 */
export interface RedemptionRecord {
  id: number
  code: string
  campaign_name: string
  coupon_type: CouponType
  benefit_text: string
  order_amount: string | null
  discount_amount: string | null
  payable_amount: string | null
  used_at: string
  store_name: string | null
}

export interface VerifierRedemptions {
  verifier: VerifierBrief
  items: RedemptionRecord[]
  total: number
  page: number
  page_size: number
}

export interface OperatorBrief {
  id: number
  username: string
  display_name: string
  phone: string | null
  status: AccountStatus
}

/** 运营发布的活动行（FR-071）。界面称「发布的券」，数据粒度是活动 */
export interface OperatorCampaign {
  id: number
  name: string
  category: Category
  coupon_type: CouponType
  benefit_text: string
  total_stock: number
  claimed_count: number
  used_count: number
  remaining_stock: number
  status: CampaignStatus
  start_at: string
  end_at: string
}

export interface OperatorCampaigns {
  operator: OperatorBrief
  items: OperatorCampaign[]
  total: number
  page: number
  page_size: number
}

export interface Campaign {
  id: number
  name: string
  category: Category
  coupon_type: CouponType
  face_value: string | null
  min_order_amount: string
  discount_percent: number | null
  max_discount_amount: string | null
  /** 优惠描述由后端统一生成，前端直接展示，避免两端各拼一套文案 */
  benefit_text: string
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
  coupon_type: CouponType
  face_value: string | null
  min_order_amount: string
  discount_percent: number | null
  max_discount_amount: string | null
  benefit_text: string
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
  coupon_type: CouponType
  face_value: string | null
  min_order_amount: string
  benefit_text: string
  status: 'UNUSED' | 'USED'
  /** 派生值：可用 / 已核销 / 已过期。"已过期"不落库 */
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
  coupon_type: CouponType
  face_value: string | null
  benefit_text: string
  remaining_stock: number
  reason: string
}

export interface RecommendationResult {
  items: Recommendation[]
  degraded: boolean
  degrade_reason: string | null
  cold_start: boolean
  /** AI 对用户需求的理解概述，仅「按需求找券」接口返回；自动推荐为 null/缺省 */
  analysis?: string | null
}

export interface RedeemCheck {
  code: string
  campaign_name: string
  coupon_type: CouponType
  benefit_text: string
  face_value: string | null
  min_order_amount: string
  discount_percent: number | null
  max_discount_amount: string | null
  display_status: string
  owner: string
  redeemable: boolean
  reason: string | null
}

export interface RedeemResult {
  code: string
  benefit_text: string
  order_amount: string
  discount_amount: string
  payable_amount: string
  used_at: string
  used_by: string
  store_name: string | null
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
  redeem_rate: number | null
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
  USER: '会员',
  VERIFIER: '核销人员',
  ADMIN: '管理员',
}

export const COUPON_TYPE_LABEL: Record<CouponType, string> = {
  CASH: '满减券',
  DISCOUNT: '折扣券',
}

/** 错误码 → 用户文案。按 code 分支，文案可调整而 code 是契约 */
export const ERROR_MESSAGE: Record<string, string> = {
  OUT_OF_STOCK: '库存不足',
  PER_USER_LIMIT_REACHED: '已达领取上限',
  CAMPAIGN_NOT_ACTIVE: '活动未开始或已结束',
  COUPON_ALREADY_USED: '该券已核销',
  COUPON_EXPIRED: '该券已过期',
  COUPON_NOT_FOUND: '券码不存在',
  ORDER_AMOUNT_BELOW_THRESHOLD: '订单金额未达使用门槛',
  RISK_BLOCKED: '操作过于频繁，请稍后再试',
  RISK_MANUAL_REVIEW: '账号存在异常，需人工审核后方可领取',
  STOCK_CANNOT_DECREASE: '库存只能追加',
  USERNAME_TAKEN: '该账号已被使用',
  STORE_NOT_FOUND: '门店不存在',
  ACCOUNT_PENDING_APPROVAL: '账号正在审核中',
  ACCOUNT_REJECTED: '账号申请未通过',
  FORBIDDEN: '无权访问该资源',
}
