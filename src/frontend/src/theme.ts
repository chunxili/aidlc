import type { ThemeConfig } from 'antd'

/**
 * 设计令牌。
 *
 * 刻意避开 Ant Design 默认的 #1677ff：默认主色辨识度低，
 * 一眼就能看出是未做品牌化的脚手架。改用偏深的品牌蓝配琥珀色强调色。
 */
export const theme: ThemeConfig = {
  token: {
    colorPrimary: '#1b4b91',
    colorInfo: '#1b4b91',
    colorSuccess: '#0f7b55',
    colorWarning: '#b7791f',
    colorError: '#c0362c',
    colorTextBase: '#1c2434',
    colorBgLayout: '#f4f6f9',
    borderRadius: 4,
    fontSize: 14,
    fontFamily:
      '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
    controlHeight: 34,
    wireframe: false,
  },
  components: {
    Layout: {
      headerBg: '#ffffff',
      headerHeight: 56,
      siderBg: '#132441',
      bodyBg: '#f4f6f9',
    },
    Menu: {
      darkItemBg: '#132441',
      darkSubMenuItemBg: '#0e1c33',
      darkItemSelectedBg: '#1b4b91',
      darkItemHoverBg: '#1a2f52',
      itemMarginInline: 8,
      itemBorderRadius: 4,
    },
    Card: {
      headerFontSize: 15,
      paddingLG: 20,
    },
    Table: {
      headerBg: '#fafbfc',
      headerColor: '#5a6478',
      rowHoverBg: '#f5f8fd',
      cellPaddingBlock: 11,
    },
    Statistic: {
      titleFontSize: 13,
      contentFontSize: 26,
    },
    Descriptions: {
      labelBg: '#fafbfc',
    },
    Button: {
      fontWeight: 500,
    },
  },
}

export const BRAND = {
  name: '惠码',
  suffix: '优惠券中心',
  full: '惠码 · 优惠券中心',
}
