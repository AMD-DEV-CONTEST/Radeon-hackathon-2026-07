import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { ShiduApp } from "./app/ShiduApp";
import "./styles/fusheng.css";

createRoot(document.getElementById("root")!).render(<StrictMode><ShiduApp /></StrictMode>);
