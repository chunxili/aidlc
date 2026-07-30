/**
 * 券码二维码弹窗（会员端出示用）。
 *
 * 二维码内容就是 10 位券码明文本身，不套 URL 也不套 JSON：
 * 券码本身已是唯一凭证，包一层只会让核销端多一处解析分支。
 * 纠错等级取 M —— 手机屏幕反光、脏污时容错更好，10 位内容依然是最小版本。
 */

import { Modal, Typography } from 'antd'
import { QRCodeCanvas } from 'qrcode.react'
import type { Coupon } from '../api/types'

export function CouponQrModal({
  coupon,
  onClose,
}: {
  coupon: Coupon | null
  onClose: () => void
}) {
  return (
    <Modal open={!!coupon} onCancel={onClose} footer={null} width={360} title="出示券码">
      {coupon && (
        <div style={{ textAlign: 'center', padding: '8px 0 4px' }}>
          <div
            style={{
              display: 'inline-block',
              padding: 12,
              background: '#fff',
              border: '1px solid #e8ebf0',
              borderRadius: 6,
            }}
          >
            <QRCodeCanvas
              value={coupon.code}
              size={220}
              level="M"
              marginSize={2}
              title={`券码 ${coupon.code}`}
            />
          </div>

          <div style={{ marginTop: 14 }}>
            <Typography.Text className="mono" strong style={{ fontSize: 22 }}>
              {coupon.code}
            </Typography.Text>
          </div>

          <Typography.Paragraph style={{ margin: '6px 0 0' }}>
            {coupon.campaign_name} · <Typography.Text strong>{coupon.benefit_text}</Typography.Text>
          </Typography.Paragraph>

          <Typography.Text
            type={coupon.display_status === '可用' ? 'warning' : 'secondary'}
            style={{ fontSize: 12 }}
          >
            {coupon.display_status === '可用'
              ? `有效期至 ${new Date(coupon.expires_at).toLocaleString('zh-CN')}`
              : `该券${coupon.display_status}，无法再次核销`}
          </Typography.Text>

          <Typography.Paragraph type="secondary" style={{ fontSize: 12, margin: '12px 0 0' }}>
            请将二维码对准门店的核销扫码框，或直接口述券码。
          </Typography.Paragraph>
        </div>
      )}
    </Modal>
  )
}
