import type { CSSProperties, ReactNode } from "react";

// Dock.jsx is vendored JS; without this, TS infers `items = []` as never[] and rejects every real item.
export type DockItem = {
  icon?: ReactNode;
  label?: string;
  badge?: number | string | boolean;
  active?: boolean;
  onClick?: () => void;
  separator?: boolean;
};

export default function Dock(props: {
  items?: DockItem[];
  position?: "bottom" | "top" | "left" | "right";
  showIndicators?: boolean;
  style?: CSSProperties & Record<`--${string}`, string>;
}): ReactNode;
