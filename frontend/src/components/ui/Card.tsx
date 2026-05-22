import type { ReactNode } from "react";

interface CardProps {
  title?: string;
  description?: string;
  className?: string;
  children: ReactNode;
  action?: ReactNode;
}

export function Card({ title, description, className = "", children, action }: CardProps) {
  return (
    <section className={`card ${className}`.trim()}>
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
