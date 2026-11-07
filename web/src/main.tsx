import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { createWebSocketAdapter } from "./adapter";
import "./index.css";

// Day 8: connect the redesigned UI to the FlowMini engine over WebSocket.
// When a real adapter is injected the Preview switch disappears (the engine is
// the single source of truth — the UI never synthesises transcripts).
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App adapter={createWebSocketAdapter()} />
  </StrictMode>,
);
