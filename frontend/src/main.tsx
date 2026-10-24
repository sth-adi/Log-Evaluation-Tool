import React from "react";
import ReactDOM from "react-dom/client";
import "@fontsource-variable/geist";
import "uplot/dist/uPlot.min.css";
import "./styles/tokens.css";
import "./styles/app.css";
import App from "./App";

// Canvas text needs the font loaded before the first plot is drawn.
document.fonts
  .load('500 12px "Geist Variable"')
  .catch((e) => console.warn("Could not preload the font; plots draw with the fallback font until it loads.", e))
  .finally(() => {
    ReactDOM.createRoot(document.getElementById("root")!).render(
      <React.StrictMode>
        <App />
      </React.StrictMode>,
    );
  });
