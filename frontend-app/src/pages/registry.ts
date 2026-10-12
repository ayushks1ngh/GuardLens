import type { ComponentType } from "react";
import type { Meta } from "../types";
import { HealthPage } from "./HealthPage";
import { RulesPage } from "./RulesPage";

export interface PageDef { key: string; label: string; component: ComponentType<{ meta: Meta | null }> }

/** Add a screen by appending one line here; App.tsx never needs to change. */
export const PAGES: PageDef[] = [
  { key: "rules", label: "Rules", component: RulesPage },
  { key: "health", label: "Health", component: HealthPage },
];
