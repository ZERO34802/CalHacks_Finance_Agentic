// Reviewer app entry. Mantine supplies the components; the theme carries the brand teal (#0E6E76).
import "@mantine/core/styles.css";
import "@mantine/notifications/styles.css";
import "@mantine/charts/styles.css";
import "@mantine/spotlight/styles.css";
import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import "@fontsource/saira-stencil-one";
import { createTheme, MantineProvider } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import ReviewApp from "./ReviewApp";

const theme = createTheme({
  primaryColor: "brand",
  primaryShade: 7,
  colors: {
    brand: ["#e6f4f5", "#cfe7e9", "#9ccfd3", "#66b6bd", "#3aa1aa", "#1e939d", "#13838c", "#0e6e76", "#0a5e65", "#044f55"],
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
