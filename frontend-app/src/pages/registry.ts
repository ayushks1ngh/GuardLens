import type { ComponentType } from "react";
import type { Meta } from "../types";
import { HealthPage } from "./HealthPage";
import { FacesPage } from "./FacesPage";
import { NotifiersPage } from "./NotifiersPage";
import { RecordingPage } from "./RecordingPage";
import { ReportsPage } from "./ReportsPage";
import { CamerasPage } from "./CamerasPage";
import { EventsPage } from "./EventsPage";
import { LivePage } from "./LivePage";
import { RulesPage } from "./RulesPage";
import { ZonesPage } from "./ZonesPage";
import { AgentsPage } from "./AgentsPage";
import { SearchPage } from "./SearchPage";
import { SecurityPage } from "./SecurityPage";

export interface PageDef { key: string; label: string; component: ComponentType<{ meta: Meta | null }>; group?: "settings" }

/** Add a screen by appending one line here; App.tsx never needs to change.
 *  Everyday screens sit in the left menu; `group: "settings"` ones appear as tabs under Settings. */
export const PAGES: PageDef[] = [
  { key: "live", label: "Live", component: LivePage },
  { key: "events", label: "Events", component: EventsPage },
  { key: "search", label: "Find footage", component: SearchPage },
  { key: "reports", label: "Reports", component: ReportsPage },
  { key: "cameras", label: "Cameras", component: CamerasPage, group: "settings" },
  { key: "rules", label: "Rules", component: RulesPage, group: "settings" },
  { key: "zones", label: "Zones", component: ZonesPage, group: "settings" },
  { key: "faces", label: "Faces", component: FacesPage, group: "settings" },
  { key: "notifiers", label: "Notifications", component: NotifiersPage, group: "settings" },
  { key: "recording", label: "Recording", component: RecordingPage, group: "settings" },
  { key: "agents", label: "AI helpers", component: AgentsPage, group: "settings" },
  { key: "security", label: "Security", component: SecurityPage, group: "settings" },
  { key: "health", label: "Health", component: HealthPage, group: "settings" },
];

export const MAIN_PAGES = PAGES.filter((p) => !p.group);
export const SETTINGS_PAGES = PAGES.filter((p) => p.group === "settings");
