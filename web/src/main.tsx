import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { UiProvider } from "./components/ui";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <UiProvider>
      <App />
    </UiProvider>
  </StrictMode>,
);

// Lets the browser offer "Install Porthaven" (its own window, dock icon and badge).
if ("serviceWorker" in navigator && location.hostname.match(/^(localhost|127\.0\.0\.1|\[::1\])$/)) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
