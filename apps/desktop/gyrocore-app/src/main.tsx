import ReactDOM from "react-dom/client";
import App from "./App";
import { pwaUpdates } from "./pwa/update";
import "./index.css";

// Register prompt-based SW update controller (no-op when SW unavailable).
void pwaUpdates.getState();

ReactDOM.createRoot(document.getElementById("root")!).render(<App />);
