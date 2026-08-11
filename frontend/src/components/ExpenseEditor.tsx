import { useEffect, useState } from "react";
import {
  Alert, Box, Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, Divider,
  FormControlLabel, MenuItem, Stack, TextField, Typography,
} from "@mui/material";
import { CheckRounded, DeleteOutlineRounded, ReplayRounded } from "@mui/icons-material";
import { api, Category, Expense, PaymentMethod, money } from "../api";

export default function ExpenseEditor({expense, open, onClose, onChanged}: {
  expense: Expense | null; open: boolean; onClose: () => void; onChanged: () => void;
}) {
  const [draft, setDraft] = useState<Expense | null>(expense);
  const [categories, setCategories] = useState<Category[]>([]);
  const [methods, setMethods] = useState<PaymentMethod[]>([]);
  const [remember, setRemember] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { setDraft(expense); setRemember(false); setError(""); }, [expense]);
  useEffect(() => { if (open) Promise.all([api<Category[]>("/api/categories"), api<PaymentMethod[]>("/api/payment-methods")]).then(([c,m])=>{setCategories(c);setMethods(m)}); }, [open]);
  if (!draft) return null;
  const set = (key: keyof Expense, value: unknown) => setDraft({...draft, [key]: value});
  const save = async (accept = false) => {
    setBusy(true); setError("");
    const payload = {
      expense_date:draft.expense_date, merchant:draft.merchant, original_amount:draft.original_amount,
      original_currency:draft.original_currency, category_id:draft.category_id, payment_method_id:draft.payment_method_id,
      scope:draft.scope, location:draft.location, department:draft.department, trip_name:draft.trip_name,
      refundable:draft.refundable, memo:draft.memo, quickbooks_category:draft.quickbooks_category,
      quickbooks_class:draft.quickbooks_class, quickbooks_customer_job:draft.quickbooks_customer_job,
      quickbooks_location:draft.quickbooks_location, quickbooks_subprogram:draft.quickbooks_subprogram,
      quickbooks_vendor:draft.quickbooks_vendor, accept, remember_merchant: accept && remember,
    };
    try { await api(`/api/expenses/${draft.id}`, {method:"PATCH", body:JSON.stringify(payload)}); onChanged(); onClose(); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not save"); }
    finally { setBusy(false); }
  };
  const remove = async () => { if (!confirm("Move this expense out of the ledger?")) return; await api(`/api/expenses/${draft.id}`, {method:"DELETE"}); onChanged(); onClose(); };
  const reprocess = async () => { setBusy(true); try { await api(`/api/expenses/${draft.id}/reprocess`, {method:"POST"}); onChanged(); onClose(); } catch(e) {setError(e instanceof Error ? e.message : "Could not reprocess")} finally {setBusy(false)} };
  const field = (key: keyof Expense, label: string) => <TextField label={label} value={(draft[key] as string | null) ?? ""} onChange={(e)=>set(key,e.target.value || null)} />;
  return <Dialog open={open} onClose={busy ? undefined : onClose} fullScreen={window.innerWidth < 760} fullWidth maxWidth="lg">
    <DialogTitle sx={{display:"flex", justifyContent:"space-between", alignItems:"baseline"}}><span>{draft.merchant || "Review receipt"}</span><Typography color="text.secondary">{money(draft.amount)}</Typography></DialogTitle>
    <DialogContent dividers><Box sx={{display:"grid", gridTemplateColumns:{xs:"1fr", md:"minmax(300px, .85fr) minmax(360px, 1.15fr)"}, gap:3}}>
      <Box>{draft.receipt_id ? <img className="receipt-preview" src={`/api/receipts/${draft.receipt_id}/preview`} alt="Receipt preview" /> : <Box className="empty-state">No receipt preview</Box>} {draft.receipt_url && <Button href={draft.receipt_url} target="_blank" sx={{mt:1}}>Open original</Button>}</Box>
      <Stack spacing={2}>{error && <Alert severity="error">{error}</Alert>}
        <Box sx={{display:"grid", gridTemplateColumns:"1fr 1fr", gap:2}}><TextField type="date" label="Date" InputLabelProps={{shrink:true}} value={draft.expense_date || ""} onChange={(e)=>set("expense_date",e.target.value || null)} />{field("merchant","Merchant")}{field("original_amount","Original amount")}{field("original_currency","Currency")}</Box>
        <TextField select label="Category" value={draft.category_id || ""} onChange={(e)=>set("category_id", e.target.value || null)}>{categories.map(c=><MenuItem key={c.id} value={c.id}>{c.name} · {c.scope}</MenuItem>)}</TextField>
        <Box sx={{display:"grid", gridTemplateColumns:"1fr 1fr", gap:2}}><TextField select label="Payment method" value={draft.payment_method_id || ""} onChange={(e)=>set("payment_method_id",e.target.value || null)}><MenuItem value="">None</MenuItem>{methods.map(m=><MenuItem key={m.id} value={m.id}>{m.name}</MenuItem>)}</TextField><TextField select label="Scope" value={draft.scope} onChange={(e)=>set("scope",e.target.value)}>{["personal","business","unknown"].map(s=><MenuItem key={s} value={s}>{s}</MenuItem>)}</TextField></Box>
        <Box sx={{display:"grid", gridTemplateColumns:"1fr 1fr", gap:2}}>{field("location","Location")}{field("department","Department")}{field("trip_name","Trip name")}<FormControlLabel control={<Checkbox checked={draft.refundable} onChange={(e)=>set("refundable",e.target.checked)} />} label="Refundable" /></Box>
        <TextField multiline minRows={2} label="Memo" value={draft.memo || ""} onChange={(e)=>set("memo",e.target.value || null)} />
        <Divider><Typography variant="caption">QUICKBOOKS MAPPINGS</Typography></Divider>
        <Box sx={{display:"grid", gridTemplateColumns:"1fr 1fr", gap:2}}>{field("quickbooks_category","Category")}{field("quickbooks_class","Class")}{field("quickbooks_customer_job","Customer / Job")}{field("quickbooks_location","Location")}{field("quickbooks_subprogram","Subprogram")}{field("quickbooks_vendor","Vendor")}</Box>
        <FormControlLabel control={<Checkbox checked={remember} onChange={(e)=>setRemember(e.target.checked)} />} label="Remember for this merchant" />
        <Typography variant="caption" color="text.secondary">Future matching receipts inherit this category, payment method, and scope.</Typography>
        <Typography variant="caption" color="text.secondary">AI confidence {Math.round(draft.confidence*100)}% · {draft.status.replace("_"," ")}</Typography>
      </Stack>
    </Box></DialogContent>
    <DialogActions sx={{p:2, flexWrap:"wrap"}}><Button color="error" startIcon={<DeleteOutlineRounded />} onClick={remove}>Delete</Button><Button startIcon={<ReplayRounded />} onClick={reprocess} disabled={busy}>Reprocess</Button><Box sx={{flex:1}}/><Button onClick={onClose}>Cancel</Button><Button onClick={()=>save(false)} disabled={busy}>Save</Button><Button variant="contained" startIcon={<CheckRounded />} onClick={()=>save(true)} disabled={busy}>Accept</Button></DialogActions>
  </Dialog>;
}
