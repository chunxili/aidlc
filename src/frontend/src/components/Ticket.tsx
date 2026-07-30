/**
 * 登录 / 注册两页共用的外壳：一张印刷券。
 *
 * 左边是券身（品牌与说明），右边是存根（表单），中间一道骑缝齿孔，
 * 骑缝处盖章。两页共用同一外壳，改一处两页一致。
 */

import { ConfigProvider } from 'antd'
import type { ReactNode } from 'react'
import { BRAND } from '../theme'

/** 券身与存根的表单控件用墨蓝，不跟随全局的品牌蓝，避免两套蓝并置。 */
const INK = '#1b2e4a'

interface TicketProps {
  /** 券身主标题 */
  headline: ReactNode
  /** 券身正文，标题下方 */
  children?: ReactNode
  /** 存根标题，例如「登录」 */
  stubTitle: string
  /** 存根标题右侧的跳转入口 */
  stubAction: ReactNode
  /** 存根内容，通常是表单 */
  stub: ReactNode
}

export function Ticket({ headline, children, stubTitle, stubAction, stub }: TicketProps) {
  return (
    <ConfigProvider theme={{ token: { colorPrimary: INK, colorInfo: INK, borderRadius: 2 } }}>
      <div className="tk-stage">
        <div className="tk">
          <span className="tk__perf" aria-hidden="true" />
          <span className="tk__notch tk__notch--top" aria-hidden="true" />
          <span className="tk__notch tk__notch--bottom" aria-hidden="true" />

          <section className="tk__body">
            <div className="tk__edge" aria-hidden="true">
              <span className="tk__edge-text">HUIMA COUPON CENTER</span>
            </div>

            <div className="tk__over">优惠券发放与核销系统</div>

            <div className="tk__brand">
              <span className="brand__mark">惠</span>
              <span className="tk__brand-text">{BRAND.full}</span>
            </div>

            <h1 className="tk__head">{headline}</h1>
            {children}

            <div className="tk__body-foot">
              <div className="tk__chop" aria-hidden="true">
                <span className="tk__chop-name">{BRAND.name}</span>
                <span className="tk__chop-rule" />
                <span className="tk__chop-sub">GUANGZHOU</span>
              </div>
            </div>
          </section>

          <main className="tk__stub">
            <div className="tk__stub-head">
              <h2 className="tk__stub-title">{stubTitle}</h2>
              {stubAction}
            </div>
            {stub}
            <div className="tk__stub-copyright">© 2026 {BRAND.full}</div>
          </main>
        </div>
      </div>
    </ConfigProvider>
  )
}
