import type { ReactNode, CSSProperties } from 'react';

interface PanelProps {
  title?: ReactNode;
  extra?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClass?: string;
  noPadding?: boolean;
  secondary?: boolean;
  borderless?: boolean;
  style?: CSSProperties;
}

const GLASS: CSSProperties = {
  background: 'linear-gradient(180deg, rgba(23,42,59,0.88), rgba(8,17,25,0.92))',
  border: '1px solid rgba(148,186,215,0.18)',
  boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.04), 0 18px 48px rgba(0,0,0,0.34)',
  backdropFilter: 'blur(10px)',
  borderRadius: 18,
};

export default function Panel({
  title,
  extra,
  children,
  className = '',
  bodyClass = '',
  noPadding = false,
  borderless = false,
  style,
}: PanelProps) {
  const merged: CSSProperties = {
    ...GLASS,
    ...(borderless ? { border: 'none', boxShadow: 'none' } : {}),
    ...style,
  };

  return (
    <div
      className={`flex flex-col overflow-hidden ${className}`}
      style={merged}
    >
      {title && (
        <div
          className="flex items-center justify-between shrink-0"
          style={{
            height: 40,
            padding: '0 18px',
            borderBottom: '1px solid rgba(148,186,215,0.12)',
          }}
        >
          <span
            style={{
              fontSize: 13,
              fontWeight: 600,
              letterSpacing: '0.04em',
              color: '#d7efff',
            }}
          >
            {title}
          </span>
          {extra}
        </div>
      )}
      <div
        className={`flex-1 min-h-0 overflow-auto ${bodyClass}`}
        style={noPadding ? undefined : { padding: '14px 18px' }}
      >
        {children}
      </div>
    </div>
  );
}
