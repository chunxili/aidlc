import type { ReactNode } from 'react'

export function PageHeader({
  title,
  description,
  extra,
}: {
  title: string
  description?: string
  extra?: ReactNode
}) {
  return (
    <div className="page-head" style={{ display: 'flex', alignItems: 'flex-start', gap: 16 }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <h1 className="page-head__title">{title}</h1>
        {description && <p className="page-head__desc">{description}</p>}
      </div>
      {extra && <div style={{ flex: '0 0 auto', paddingTop: 2 }}>{extra}</div>}
    </div>
  )
}
