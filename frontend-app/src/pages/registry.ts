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
import { AssistantPage } from "./AssistantPage";

export interface PageDef { key: string; label: string; component: ComponentType<{ meta: Meta | null }> }

/** Add a screen by appending one line here; App.tsx never needs to change. */
export const PAGES: PageDef[] = [
  { key: "live", label: "Live", component: LivePage },
  { key: "events", label: "Events", component: EventsPage },
  { key: "cameras", label: "Cameras", component: CamerasPage },
  { key: "rules", label: "Rules", component: RulesPage },
  { key: "zones", label: "Zones", component: ZonesPage },
  { key: "faces", label: "Faces", component: FacesPage },
  { key: "notifiers", label: "Notifications", component: NotifiersPage },
  { key: "recording", label: "Recording", component: RecordingPage },
  { key: "reports", label: "Reports", component: ReportsPage },
  { key: "assistant", label: "Ask GuardLens", component: AssistantPage },
  { key: "agents", label: "Agents", component: AgentsPage },
  { key: "health", label: "Health", component: HealthPage },
];
