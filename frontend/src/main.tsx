import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import { applyTheme, readTheme } from "./ui/theme";
import "./ui/tokens.css";
import "./styles.css";
import "./ui/foundation.css";
applyTheme(readTheme());
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
