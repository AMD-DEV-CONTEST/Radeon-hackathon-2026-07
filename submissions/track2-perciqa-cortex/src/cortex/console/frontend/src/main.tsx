import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { ThemeProvider, createTheme, CssBaseline, GlobalStyles } from "@mui/material";
import "@fontsource/space-grotesk/500.css";
import "@fontsource/space-grotesk/600.css";
import "@fontsource/space-grotesk/700.css";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "@fontsource/ibm-plex-mono/600.css";
import App from "./App";
import "./index.css";

const theme = createTheme({
  palette: {
    mode: "dark",
    primary: { main: "#34d6c8" },
    secondary: { main: "#9b7bff" },
    success: { main: "#3ddc97" },
    error: { main: "#ff5d73" },
    warning: { main: "#f5a524" },
    background: { default: "#0e1218", paper: "#161c26" },
    divider: "rgba(150,170,200,.08)",
  },
  typography: {
    fontFamily: '"IBM Plex Sans", -apple-system, sans-serif',
    h1: {
      fontFamily: '"Space Grotesk", sans-serif',
      fontWeight: 700,
      fontSize: "2.25rem",
      lineHeight: 1.2,
      letterSpacing: "-0.02em",
    },
    h2: {
      fontFamily: '"Space Grotesk", sans-serif',
      fontWeight: 600,
      fontSize: "1.75rem",
      lineHeight: 1.25,
      letterSpacing: "-0.02em",
    },
    h3: {
      fontFamily: '"Space Grotesk", sans-serif',
      fontWeight: 600,
      fontSize: "1.375rem",
      lineHeight: 1.3,
    },
    h4: {
      fontFamily: '"IBM Plex Sans", sans-serif',
      fontWeight: 600,
      fontSize: "1.125rem",
    },
    h5: {
      fontFamily: '"IBM Plex Sans", sans-serif',
      fontWeight: 600,
      fontSize: "1rem",
    },
    h6: {
      fontFamily: '"IBM Plex Sans", sans-serif',
      fontWeight: 600,
      fontSize: "0.9375rem",
    },
    subtitle2: {
      fontFamily: '"IBM Plex Mono", monospace',
      fontWeight: 500,
      fontSize: "0.75rem",
      fontVariantNumeric: "tabular-nums",
    },
    body1: { fontWeight: 400, fontSize: "0.9375rem", lineHeight: 1.5, color: "#c2cbda" },
    body2: { fontWeight: 400, fontSize: "0.8125rem", lineHeight: 1.5, color: "#c2cbda" },
    caption: {
      fontFamily: '"IBM Plex Mono", monospace',
      fontSize: "0.6875rem",
      fontVariantNumeric: "tabular-nums",
      color: "#8a94a8",
    },
    overline: {
      fontFamily: '"IBM Plex Mono", monospace',
      fontWeight: 500,
      fontSize: "0.65625rem",
      letterSpacing: "0.18em",
      textTransform: "uppercase",
      color: "#8a94a8",
    },
  },
  shape: { borderRadius: 10 },
  components: {
    MuiCard: {
      styleOverrides: {
        root: {
          backgroundImage: "none",
          borderRadius: "var(--r-md, 10px)",
          transition: "box-shadow var(--t, 0.26s) var(--ease, cubic-bezier(.22,.61,.36,1)), transform var(--t, 0.26s) var(--ease, cubic-bezier(.22,.61,.36,1))",
          "&:hover": {
            boxShadow: "0 1px 0 rgba(255,255,255,.04), 0 8px 24px -8px rgba(0,0,0,.7)",
            transform: "translateY(-2px)",
          },
        },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: { textTransform: "none", borderRadius: 8, fontWeight: 500 },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: { borderRadius: 999 },
        label: { fontWeight: 500, fontSize: "0.6875rem" },
      },
    },
    MuiInputBase: {
      styleOverrides: {
        root: { borderRadius: 8 },
      },
    },
    MuiDrawer: {
      styleOverrides: {
        paper: { background: "var(--bg-rail, #11161e)", borderRight: "1px solid var(--line, rgba(150,170,200,.08))" },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: { background: "var(--bg-rail, #11161e) !important", backgroundImage: "none !important" },
      },
    },
    MuiListItemButton: {
      styleOverrides: {
        root: {
          borderRadius: "var(--r-sm, 6px)",
          margin: "2px 8px",
          "&.Mui-selected": {
            background: "rgba(52,214,200,.12)",
            "&:hover": { background: "rgba(52,214,200,.18)" },
          },
        },
      },
    },
    MuiListItemIcon: {
      styleOverrides: {
        root: { minWidth: 36, color: "#8a94a8" },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: { backgroundImage: "none" },
      },
    },
    MuiTableCell: {
      styleOverrides: {
        root: { borderBottom: "1px solid rgba(150,170,200,.08)" },
      },
    },
    MuiLinearProgress: {
      styleOverrides: {
        root: { borderRadius: 4, background: "rgba(150,170,200,.08)" },
      },
    },
    MuiCircularProgress: {
      styleOverrides: {
        root: { "& .MuiCircularProgress-track": { color: "rgba(150,170,200,.08)" } },
      },
    },
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <ThemeProvider theme={theme}>
    <CssBaseline />
    <GlobalStyles
      styles={{
        ".app-container": {
          position: "relative",
          minHeight: "100vh",
          "&::before": {
            content: '""',
            position: "fixed",
            inset: 0,
            pointerEvents: "none",
            zIndex: 0,
            backgroundImage:
              "linear-gradient(rgba(150,170,200,.06) 1px, transparent 1px), linear-gradient(90deg, rgba(150,170,200,.06) 1px, transparent 1px)",
            backgroundSize: "56px 56px",
            WebkitMask: "radial-gradient(130% 100% at 50% -10%, #000 25%, transparent 78%)",
            mask: "radial-gradient(130% 100% at 50% -10%, #000 25%, transparent 78%)",
            opacity: 0.6,
          },
          "&::after": {
            content: '""',
            position: "fixed",
            inset: 0,
            pointerEvents: "none",
            zIndex: 0,
            background:
              "radial-gradient(70% 50% at 88% 112%, hsl(var(--threat-h, 176) 70% 45% / 0.10), transparent 70%), radial-gradient(50% 40% at 6% -8%, hsl(220 60% 50% / 0.06), transparent 70%)",
            transition: "background 1.4s cubic-bezier(.22,.61,.36,1)",
          },
          "& > *": { position: "relative", zIndex: 1 },
        },
      }}
    />
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </ThemeProvider>
);
