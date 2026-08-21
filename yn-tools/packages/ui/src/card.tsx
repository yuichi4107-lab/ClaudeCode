import React from "react";

export function Card({
  title,
  children,
}: {
  title?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        border: "1px solid #e2e8f0",
        borderRadius: 8,
        padding: "1.5rem",
        marginBottom: "1rem",
      }}
    >
      {title && <h3 style={{ marginTop: 0 }}>{title}</h3>}
      {children}
    </div>
  );
}
