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

export default function Panel({
  title,
  extra,
  children,
  className = '',
  bodyClass = '',
  noPadding = false,
  secondary = false,
  borderless = false,
  style,
}: PanelProps) {
  const border = borderless
    ? 'border-transparent'
    : 'border-[rgba(255,255,255,0.035)]';

  return (
    <div
      className={`bg-bg-panel border rounded-panel flex flex-col overflow-hidden ${border} ${className}`}
      style={style}
    >
      {title && (
        <div
          className="flex items-center justify-between shrink-0"
          style={{
            height: 36,
            padding: '0 16px',
            borderBottom: '1px solid rgba(255,255,255,0.05)',
          }}
        >
          <span
            className="text-t2 tracking-wide"
            style={{ fontSize: secondary ? 11 : 12, fontWeight: secondary ? 400 : 500 }}
          >
            {title}
          </span>
          {extra}
        </div>
      )}
      <div
        className={`flex-1 min-h-0 overflow-auto ${bodyClass}`}
        style={noPadding ? undefined : { padding: '12px 16px' }}
      >
        {children}
      </div>
    </div>
  );
}
