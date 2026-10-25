// Reviewer app entry. Mantine supplies the components; the theme carries the brand teal (#0E6E76, the logo colour).
// The palette is one family from the logo: teal (actions, needs review, approved), aqua (hold, warnings),
// slate (settled, scheduled, info) and teal-tinted greys. Red is kept for danger only (fraud, payment blocked).
// Mantine's other named colours are remapped onto that family, so every page stays on-brand without layout changes.
import "@mantine/core/styles.css";
import "@mantine/notifications/styles.css";
import "@mantine/charts/styles.css";
import "@mantine/spotlight/styles.css";
import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import "@fontsource/saira-stencil-one";
import { createTheme, MantineProvider, type MantineColorsTuple } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import ReviewApp from "./ReviewApp";

const teal: MantineColorsTuple = ["#e6f4f5", "#cfe7e9", "#9ccfd3", "#66b6bd", "#3aa1aa", "#1e939d", "#13838c", "#0e6e76", "#0a5e65", "#044f55"];
const aqua: MantineColorsTuple = ["#e8f6f5", "#d3eeec", "#a7dcd8", "#78c9c3", "#52b9b2", "#3aafa7", "#2aa199", "#1d8a83", "#15756f", "#0b605b"];
const slate: MantineColorsTuple = ["#f1f4f5", "#e2e8ea", "#c4d0d3", "#a3b4b8", "#879ca1", "#748c92", "#62797f", "#4f666c", "#43585d", "#34494e"];
const red: MantineColorsTuple = ["#fbefee", "#f3dcda", "#e6b5b0", "#d98b84", "#cf6a61", "#c9554b", "#c24a40", "#ab3c33", "#97342c", "#822a23"];
const gray: MantineColorsTuple = ["#f7f9f9", "#f0f3f4", "#e5eaeb", "#d6dddf", "#b4bfc2", "#93a1a5", "#738387", "#5b6a6e", "#3f4b4e", "#283235"];

const theme = createTheme({
  primaryColor: "brand",
  primaryShade: 7,
  colors: {
    brand: teal, teal, aqua, slate, red, gray,
    violet: teal, grape: teal, indigo: teal,      // needs a person: the brand colour
    yellow: aqua, orange: aqua,                    // hold, warnings
    green: slate, blue: slate, cyan: slate,        // settled, scheduled, informational
    pink: gray, lime: gray,                        // avatar and chart fillers
  },
  fontFamily: "'Geist Variable', system-ui, sans-serif",
  fontFamilyMonospace: "'Geist Mono Variable', ui-monospace, monospace",
  headings: { fontFamily: "'Geist Variable', system-ui, sans-serif" },
  defaultRadius: "md",
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MantineProvider theme={theme}>
      <Notifications position="top-right" />
      <ReviewApp />
    </MantineProvider>
  </StrictMode>,
);
