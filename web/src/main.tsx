import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { createBridgeAPIIAdapter } from "./adapter";
import "./index.css";

// The pywebview window is created with js_api=BridgeAPI (see app.py), so the
// BridgeAPI instance is available as window.pywebview.api. The adapter in
// ./adapter exposes those methods to the React UI.
const adapter = createBridgeAPIIAdapter();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App adapter={adapter} />
  </StrictMode>,
);
