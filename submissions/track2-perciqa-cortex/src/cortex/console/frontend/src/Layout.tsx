import { useState, useEffect } from "react";
import AppBar from "@mui/material/AppBar";
import Box from "@mui/material/Box";
import Drawer from "@mui/material/Drawer";
import List from "@mui/material/List";
import ListItemButton from "@mui/material/ListItemButton";
import ListItemIcon from "@mui/material/ListItemIcon";
import ListItemText from "@mui/material/ListItemText";
import Toolbar from "@mui/material/Toolbar";
import Typography from "@mui/material/Typography";
import { keyframes } from "@mui/material/styles";
import Dashboard from "@mui/icons-material/Dashboard";
import Article from "@mui/icons-material/Article";
import SmartToy from "@mui/icons-material/SmartToy";
import Hub from "@mui/icons-material/Hub";
import FilterAlt from "@mui/icons-material/FilterAlt";
import Speed from "@mui/icons-material/Speed";
import Shield from "@mui/icons-material/Shield";

const pulseRing = keyframes`
  0% { transform: scale(1); opacity: 0.6; }
  50% { transform: scale(2.5); opacity: 0; }
  100% { transform: scale(1); opacity: 0; }
`;

function LiveDot({ connected }: { connected: boolean }) {
  return (
    <Box sx={{ position: "relative", display: "inline-flex", alignItems: "center" }}>
      <Box sx={{ width: 6, height: 6, borderRadius: "50%", bgcolor: connected ? "#3ddc97" : "#ff5d73", boxShadow: connected ? "0 0 6px rgba(61,220,151,.5)" : "none", position: "relative", zIndex: 1 }} />
      {connected && (
        <Box sx={{ position: "absolute", inset: "-3px", borderRadius: "50%", border: "2px solid rgba(61,220,151,.3)", animation: `${pulseRing} 2s ease-out infinite` }} />
      )}
    </Box>
  );
}

export type ViewId = "overview" | "feed" | "detail" | "provenance" | "scope" | "bench" | "attack" | "activity";

export interface LayoutProps {
  current: ViewId;
  onNavigate: (v: ViewId) => void;
  connected: boolean;
  children: React.ReactNode;
}

const NAV_ITEMS: { id: ViewId; label: string; icon: React.ReactNode }[] = [
  { id: "overview", label: "Fabric Overview", icon: <Dashboard /> },
  { id: "feed", label: "Article Feed", icon: <Article /> },
  { id: "activity", label: "Agent Activity", icon: <SmartToy /> },
  { id: "provenance", label: "Provenance Graph", icon: <Hub /> },
  { id: "scope", label: "Scope Filter", icon: <FilterAlt /> },
  { id: "bench", label: "Bench Panel", icon: <Speed /> },
  { id: "attack", label: "Attack Matrix", icon: <Shield /> },
];

const DRAWER_WIDTH = 240;

export function Layout({ current, onNavigate, connected, children }: LayoutProps) {
  const [clock, setClock] = useState(new Date());
  useEffect(() => {
    const id = setInterval(() => setClock(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <Box className="app-container" sx={{ display: "flex" }}>
      <Drawer
        variant="permanent"
        sx={{
          width: DRAWER_WIDTH,
          flexShrink: 0,
          "& .MuiDrawer-paper": {
            width: DRAWER_WIDTH,
            boxSizing: "border-box",
            position: "relative",
          },
        }}
      >
        <AppBar position="static" elevation={0}>
          <Toolbar sx={{ gap: 1.5 }}>
            <Box sx={{ width: 18, height: 18, borderRadius: "4px", bgcolor: "rgba(52,214,200,.15)", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
              <Box sx={{ width: 8, height: 8, borderRadius: "2px", bgcolor: "#34d6c8" }} />
            </Box>
            <Typography
              sx={{
                flexGrow: 1,
                fontFamily: '"Space Grotesk", sans-serif',
                fontWeight: 600,
                fontSize: "0.9375rem",
                letterSpacing: "-0.02em",
                color: "#eef2f8",
              }}
            >
              Perciqa
            </Typography>
          </Toolbar>
        </AppBar>
        <Box sx={{ display: "flex", alignItems: "center", gap: 1.5, px: 2.5, py: 1, borderBottom: "1px solid rgba(150,170,200,.08)" }}>
          <LiveDot connected={connected} />
          <Typography sx={{ fontFamily: '"IBM Plex Mono", monospace', fontSize: "0.6875rem", fontWeight: 500, color: connected ? "#3ddc97" : "#ff5d73" }}>
            {connected ? "LIVE" : "OFFLINE"}
          </Typography>
          <Typography sx={{ fontFamily: '"IBM Plex Mono", monospace', fontSize: "0.625rem", color: "#8a94a8" }}>
            {clock.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
          </Typography>
          <Box sx={{ flex: 1 }} />
          <Typography sx={{ fontFamily: '"IBM Plex Mono", monospace', fontSize: "0.6875rem", color: "#8a94a8", letterSpacing: "0.02em" }}>
            ⌘K
          </Typography>
        </Box>
        <List sx={{ pt: 0.5 }}>
          {NAV_ITEMS.map((item) => (
            <ListItemButton
              key={item.id}
              selected={current === item.id}
              onClick={() => onNavigate(item.id)}
            >
              <ListItemIcon>{item.icon}</ListItemIcon>
              <ListItemText primary={item.label} />
            </ListItemButton>
          ))}
        </List>
      </Drawer>
      <Box component="main" sx={{ flexGrow: 1, p: 3, minHeight: "100vh" }}>
        {children}
      </Box>
    </Box>
  );
}
