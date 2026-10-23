import React from "react";
import ReactDOM from "react-dom/client";
import "@fontsource/barlow-semi-condensed/400.css";
import "@fontsource/barlow-semi-condensed/500.css";
import "@fontsource/barlow-semi-condensed/600.css";
import "@fontsource/barlow-condensed/600.css";
import "uplot/dist/uPlot.min.css";
import "./styles/tokens.css";
import "./styles/app.css";
import App from "./App";

// Canvas text needs the fonts loaded before the first plot is drawn.
Promise.all([
  document.fonts.load('500 12px "Barlow Semi Condensed"'),
  document.fonts.load('600 15px "Barlow Condensed"'),
]).finally(() => {
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );
});
