import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource/saira-stencil-one";
import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import "../styles.css";
import "./proto.css";
import Proto from "./Proto";

createRoot(document.getElementById("root")!).render(<StrictMode><Proto /></StrictMode>);
