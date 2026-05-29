import type { ReactNode, CSSProperties } from "react";

interface CardProps {
  title?: string;
  description?: string;
  className?: string;
  children: ReactNode;
  action?: ReactNode;
  style?: CSSProperties;
}

export function Card({ title, description, className = "", children, action, style }: CardProps) {
  return (
    <section className={`card ${className}`.trim()} style={style}>
      {(title || description || action) && (
        <div className="card-header">
          <div>
            {title && <h2>{title}</h2>}
            {description && <p>{description}</p>}
          </div>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}
