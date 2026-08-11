import { FormEvent, useState } from "react";
import { Alert, Avatar, Box, Button, Card, CardContent, TextField, Typography } from "@mui/material";
import { LockRounded, ReceiptLongRounded } from "@mui/icons-material";
import { api } from "../api";

export default function Login({onSuccess}: {onSuccess: () => void}) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setLoading(true); setError("");
    try { await api("/api/auth/login", {method:"POST", body: JSON.stringify({password})}); onSuccess(); }
    catch (err) { setError(err instanceof Error ? err.message : "Unable to sign in"); }
    finally { setLoading(false); }
  };
  return <Box sx={{minHeight:"100vh", display:"grid", placeItems:"center", p:2, background:"radial-gradient(circle at 50% 0%, rgba(122,54,93,.24), transparent 38rem)"}}>
    <Card sx={{width:"min(440px, 100%)", borderRadius:5}}><CardContent sx={{p:{xs:3, sm:5}}}>
      <Avatar sx={{width:58, height:58, bgcolor:"primary.main", mb:3}}><ReceiptLongRounded fontSize="large" /></Avatar>
      <Typography variant="h4" className="page-title">Welcome back to Spendloom</Typography><Typography color="text.secondary" sx={{mt:1, mb:4}}>Your receipts, expenses, and spending patterns—all in one private place.</Typography>
      <Box component="form" onSubmit={submit} sx={{display:"grid", gap:2}}>{error && <Alert severity="error">{error}</Alert>}<TextField autoFocus fullWidth type="password" label="Password" value={password} onChange={(e) => setPassword(e.target.value)} InputProps={{startAdornment:<LockRounded color="action" sx={{mr:1}} />}} /><Button size="large" variant="contained" type="submit" disabled={loading || !password}>{loading ? "Signing in…" : "Open ledger"}</Button></Box>
    </CardContent></Card>
  </Box>;
}
