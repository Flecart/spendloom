import { useEffect, useMemo, useState } from "react";
import {
  AppBar, Avatar, Badge, Box, Button, CssBaseline, Drawer, IconButton, List, ListItemButton, ListItemIcon,
  ListItemText, ThemeProvider, Toolbar, Tooltip, Typography, createTheme, useMediaQuery,
} from "@mui/material";
import {
  AddRounded, CategoryRounded, DashboardRounded, DarkModeRounded, LightModeRounded, LogoutRounded,
  MenuRounded, ReceiptLongRounded, ReviewsRounded, SettingsRounded, WalletRounded,
} from "@mui/icons-material";
import { api } from "./api";
import Login from "./components/Login";
import DashboardPage from "./pages/DashboardPage";
import ExpensesPage from "./pages/ExpensesPage";
import SettingsPage from "./pages/SettingsPage";
import UploadDialog from "./components/UploadDialog";

type Page = "dashboard" | "expenses" | "review" | "settings";

export default function App() {
  const deepExpenseId = window.location.pathname.match(/^\/expenses\/([^/]+)$/)?.[1];
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [page, setPage] = useState<Page>(deepExpenseId ? "expenses" : "dashboard");
  const [mobileOpen, setMobileOpen] = useState(false);
  const [dark, setDark] = useState(() => localStorage.getItem("theme") === "dark");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [reviewCount, setReviewCount] = useState(0);
  const mobile = useMediaQuery("(max-width:900px)");

  useEffect(() => { api<{authenticated: boolean}>("/api/auth/me").then((r) => setAuthenticated(r.authenticated)).catch(() => setAuthenticated(false)); }, []);
  useEffect(() => {
    if (!authenticated) return;
    api<any>("/api/dashboard").then((data) => setReviewCount(data.review_count)).catch(() => undefined);
  }, [authenticated, refreshKey]);

  const theme = useMemo(() => createTheme({
    palette: {
      mode: dark ? "dark" : "light",
      primary: { main: "#7A365D" },
      secondary: { main: "#D96A5C" },
      background: dark ? { default: "#241A21", paper: "#30222A" } : { default: "#FBF3E7", paper: "#FFF9F0" },
    },
    shape: { borderRadius: 18 },
    typography: { fontFamily: 'Inter, ui-rounded, "SF Pro Rounded", system-ui, sans-serif', h4: { fontWeight: 780 }, h5: { fontWeight: 750 }, button: { textTransform: "none", fontWeight: 700 } },
    components: {
      MuiCard: { styleOverrides: { root: { border: dark ? "1px solid #503B46" : "1px solid #EBDCCB", boxShadow: dark ? "none" : "0 10px 35px rgba(84, 48, 54, .08)" } } },
      MuiButton: { defaultProps: { disableElevation: true } },
    },
  }), [dark]);

  if (authenticated === null) return <Box sx={{display:"grid", placeItems:"center", minHeight:"100vh"}}><ReceiptLongRounded color="primary" sx={{fontSize:64}} /></Box>;
  if (!authenticated) return <ThemeProvider theme={theme}><CssBaseline /><Login onSuccess={() => setAuthenticated(true)} /></ThemeProvider>;

  const nav = [
    { id: "dashboard" as Page, label: "Overview", icon: <DashboardRounded /> },
    { id: "expenses" as Page, label: "Expenses", icon: <ReceiptLongRounded /> },
    { id: "review" as Page, label: "Review inbox", icon: <Badge color="error" badgeContent={reviewCount}><ReviewsRounded /></Badge> },
    { id: "settings" as Page, label: "Settings", icon: <SettingsRounded /> },
  ];
  const drawer = <Box sx={{height:"100%", display:"flex", flexDirection:"column", p:2}}>
    <Box sx={{display:"flex", alignItems:"center", gap:1.5, px:1.5, py:2.5}}>
      <Avatar sx={{bgcolor:"primary.main", width:42, height:42}}><ReceiptLongRounded /></Avatar>
      <Box><Typography fontWeight={800}>Spendloom</Typography><Typography variant="caption" color="text.secondary">Private finance, gently kept</Typography></Box>
    </Box>
    <List sx={{display:"grid", gap:.75}}>{nav.map((item) => <ListItemButton key={item.id} selected={page === item.id} onClick={() => {setPage(item.id); setMobileOpen(false);}} sx={{borderRadius:3, py:1.25}}><ListItemIcon sx={{minWidth:42}}>{item.icon}</ListItemIcon><ListItemText primary={item.label} primaryTypographyProps={{fontWeight: page === item.id ? 750 : 550}} /></ListItemButton>)}</List>
    <Box sx={{mt:"auto", display:"grid", gap:1}}>
      <ListItemButton onClick={() => { const value = !dark; setDark(value); localStorage.setItem("theme", value ? "dark" : "light"); }} sx={{borderRadius:3}}><ListItemIcon sx={{minWidth:42}}>{dark ? <LightModeRounded /> : <DarkModeRounded />}</ListItemIcon><ListItemText primary={dark ? "Light theme" : "Dark theme"} /></ListItemButton>
      <ListItemButton onClick={() => api("/api/auth/logout", {method:"POST"}).finally(() => setAuthenticated(false))} sx={{borderRadius:3}}><ListItemIcon sx={{minWidth:42}}><LogoutRounded /></ListItemIcon><ListItemText primary="Sign out" /></ListItemButton>
    </Box>
  </Box>;

  return <ThemeProvider theme={theme}><CssBaseline /><Box className="app-shell">
    <AppBar position="fixed" color="inherit" elevation={0} sx={{borderBottom:1, borderColor:"divider", ml: mobile ? 0 : "264px", width: mobile ? "100%" : "calc(100% - 264px)"}}>
      <Toolbar sx={{gap:1}}>{mobile && <IconButton onClick={() => setMobileOpen(true)}><MenuRounded /></IconButton>}<Typography fontWeight={750} sx={{flexGrow:1}}>{nav.find((item) => item.id === page)?.label}</Typography><Tooltip title="Upload receipt"><Button variant="contained" startIcon={<AddRounded />} onClick={() => setUploadOpen(true)}>Add receipt</Button></Tooltip></Toolbar>
    </AppBar>
    <Box component="nav"><Drawer variant={mobile ? "temporary" : "permanent"} open={mobile ? mobileOpen : true} onClose={() => setMobileOpen(false)} ModalProps={{keepMounted:true}} sx={{"& .MuiDrawer-paper":{width:264, borderRight:1, borderColor:"divider"}}}>{drawer}</Drawer></Box>
    <Box component="main" sx={{ml: mobile ? 0 : "264px", pt:"64px"}}><Box className="main-content">
      {page === "dashboard" && <DashboardPage key={refreshKey} onReview={() => setPage("review")} />}
      {page === "expenses" && <ExpensesPage key={`expenses-${refreshKey}`} initialExpenseId={deepExpenseId} />}
      {page === "review" && <ExpensesPage key={`review-${refreshKey}`} reviewOnly onChanged={() => setRefreshKey((k) => k + 1)} />}
      {page === "settings" && <SettingsPage />}
    </Box></Box>
    <UploadDialog open={uploadOpen} onClose={() => setUploadOpen(false)} onUploaded={() => {setUploadOpen(false); setRefreshKey((k) => k + 1); setPage("review");}} />
  </Box></ThemeProvider>;
}
