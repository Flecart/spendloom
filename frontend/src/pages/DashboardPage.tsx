import { useEffect, useMemo, useState } from "react";
import { Alert, Box, Button, ButtonGroup, Card, CardContent, Chip, CircularProgress, Grid, MenuItem, Stack, TextField, Typography } from "@mui/material";
import { ArrowForwardRounded, ErrorOutlineRounded, ReceiptLongRounded, ReviewsRounded, TrendingDownRounded, TrendingUpRounded } from "@mui/icons-material";
import { Area, AreaChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, Dashboard, Scope, money } from "../api";

type RangePreset = "month" | "3m" | "6m" | "12m" | "ytd" | "all" | "custom";
type RangeState = { preset: RangePreset; date_from: string; date_to: string; scope: "" | Scope };
const key = "spendloom.dashboard.range";
const iso = (value: Date) => value.toISOString().slice(0, 10);
const monthStart = (monthsBack = 0) => { const now = new Date(); return iso(new Date(now.getFullYear(), now.getMonth() - monthsBack, 1)); };
const defaultRange = (): RangeState => ({ preset: "12m", date_from: monthStart(11), date_to: iso(new Date()), scope: "" });
function presetRange(preset: RangePreset, current: RangeState): RangeState {
  const today = iso(new Date());
  if (preset === "month") return { ...current, preset, date_from: monthStart(), date_to: today };
  if (preset === "3m") return { ...current, preset, date_from: monthStart(2), date_to: today };
  if (preset === "6m") return { ...current, preset, date_from: monthStart(5), date_to: today };
  if (preset === "12m") return { ...current, preset, date_from: monthStart(11), date_to: today };
  if (preset === "ytd") return { ...current, preset, date_from: `${new Date().getFullYear()}-01-01`, date_to: today };
  if (preset === "all") return { ...current, preset, date_from: "1900-01-01", date_to: today };
  return { ...current, preset };
}

export default function DashboardPage({onReview}:{onReview:()=>void}) {
  const [range,setRange]=useState<RangeState>(()=>{ try { return {...defaultRange(), ...JSON.parse(localStorage.getItem(key) || "{}")} } catch { return defaultRange(); } });
  const [data,setData]=useState<Dashboard|null>(null); const [error,setError]=useState("");
  const query=useMemo(()=>{const params=new URLSearchParams({date_from:range.date_from,date_to:range.date_to});if(range.scope)params.set("scope",range.scope);return params.toString()},[range]);
  useEffect(()=>{localStorage.setItem(key,JSON.stringify(range));api<Dashboard>(`/api/dashboard?${query}`).then(setData).catch(e=>setError(e.message))},[query,range]);
  const setPreset=(preset:RangePreset)=>setRange(current=>presetRange(preset,current));
  if(error) return <Alert severity="error">{error}</Alert>; if(!data) return <Box sx={{display:"grid",placeItems:"center",height:300}}><CircularProgress/></Box>;
  const previous=Number(data.previous_range_total); const current=Number(data.range_total); const direction=current>=previous;
  const title=`${new Date(`${data.date_from}T12:00:00`).toLocaleDateString(undefined,{day:"numeric",month:"short",year:"numeric"})} – ${new Date(`${data.date_to}T12:00:00`).toLocaleDateString(undefined,{day:"numeric",month:"short",year:"numeric"})}`;
  return <Stack spacing={3}>
    <Box><Typography className="eyebrow">Overview</Typography><Typography variant="h4" className="page-title">Your spending, in context</Typography><Typography color="text.secondary">Accepted expenses in <b>{title}</b>{range.scope?` · ${range.scope}`:""}.</Typography></Box>
    <Card><CardContent><Stack spacing={1.5}><ButtonGroup size="small" variant="outlined" sx={{flexWrap:"wrap",justifyContent:"flex-start"}}>{([ ["month","This month"],["3m","3 months"],["6m","6 months"],["12m","12 months"],["ytd","Year to date"],["all","All time"] ] as [RangePreset,string][]).map(([preset,label])=><Button key={preset} variant={range.preset===preset?"contained":"outlined"} onClick={()=>setPreset(preset)}>{label}</Button>)}<Button variant={range.preset==="custom"?"contained":"outlined"} onClick={()=>setPreset("custom")}>Custom</Button></ButtonGroup><Box sx={{display:"flex",gap:1,flexWrap:"wrap",alignItems:"center"}}><TextField size="small" label="From" type="date" value={range.date_from} slotProps={{inputLabel:{shrink:true}}} onChange={e=>setRange({...range,preset:"custom",date_from:e.target.value})}/><TextField size="small" label="To" type="date" value={range.date_to} slotProps={{inputLabel:{shrink:true}}} onChange={e=>setRange({...range,preset:"custom",date_to:e.target.value})}/><TextField size="small" select label="Scope" value={range.scope} onChange={e=>setRange({...range,scope:e.target.value as ""|Scope})} sx={{minWidth:140}}><MenuItem value="">All scopes</MenuItem><MenuItem value="personal">Personal</MenuItem><MenuItem value="business">Business</MenuItem><MenuItem value="unknown">Unknown</MenuItem></TextField></Box></Stack></CardContent></Card>
    {data.review_count>0&&<Alert severity="info" action={<Button onClick={onReview} endIcon={<ArrowForwardRounded/>}>Review now</Button>}>{data.review_count} receipt{data.review_count===1?"":"s"} need your attention in this range.</Alert>}
    <Grid container spacing={2}>{[
      ["Spent in selected range",money(data.range_total),direction?<TrendingUpRounded/>:<TrendingDownRounded/>],
      ["Previous equivalent range",money(data.previous_range_total),<TrendingDownRounded/>],
      ["Awaiting review",String(data.review_count),<ReviewsRounded/>],
      ["Receipts stored",String(data.receipt_count),<ReceiptLongRounded/>],
      ["Failed imports",String(data.failed_count),<ErrorOutlineRounded/>],
    ].map(([label,value,icon])=><Grid key={String(label)} size={{xs:12,sm:6,lg:label==="Spent in selected range"?4:2}}><Card className="metric-card"><CardContent><Box sx={{color:"primary.main",mb:2}}>{icon}</Box><Typography variant="h5">{value}</Typography><Typography color="text.secondary">{label}</Typography></CardContent></Card></Grid>)}</Grid>
    <Grid container spacing={2}><Grid size={{xs:12,lg:8}}><Card><CardContent><Typography variant="h6" fontWeight={750}>Monthly trend</Typography><Typography variant="body2" color="text.secondary">{title}</Typography><Box sx={{height:290,mt:2}}><ResponsiveContainer><AreaChart data={data.by_month}><defs><linearGradient id="spend" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#7a365d" stopOpacity={.35}/><stop offset="95%" stopColor="#7a365d" stopOpacity={0}/></linearGradient></defs><CartesianGrid strokeDasharray="3 3" vertical={false}/><XAxis dataKey="month" tickFormatter={v=>new Date(`${v}-02`).toLocaleDateString(undefined,{month:"short",year:"2-digit"})}/><YAxis tickFormatter={v=>`€${v}`}/><Tooltip formatter={(v)=>money(Number(v))}/><Area type="monotone" dataKey="amount" stroke="#7a365d" strokeWidth={3} fill="url(#spend)"/></AreaChart></ResponsiveContainer></Box></CardContent></Card></Grid>
      <Grid size={{xs:12,lg:4}}><Card sx={{height:"100%"}}><CardContent><Typography variant="h6" fontWeight={750}>By category</Typography>{data.by_category.length?<><Box sx={{height:210}}><ResponsiveContainer><PieChart><Pie data={data.by_category} dataKey="amount" nameKey="name" innerRadius={55} outerRadius={85}>{data.by_category.map((c,i)=><Cell key={i} fill={c.color}/>)}</Pie><Tooltip formatter={(v)=>money(Number(v))}/></PieChart></ResponsiveContainer></Box><Stack spacing={1}>{data.by_category.slice(0,5).map(c=><Box key={c.name} sx={{display:"flex",justifyContent:"space-between"}}><Chip size="small" label={c.name} sx={{borderLeft:`5px solid ${c.color}`}}/><Typography>{money(c.amount)}</Typography></Box>)}</Stack></>:<Box className="empty-state">Your category breakdown will appear here.</Box>}</CardContent></Card></Grid></Grid>
    <Card><CardContent><Typography variant="h6" fontWeight={750} sx={{mb:2}}>Top merchants</Typography><Stack spacing={1.5}>{data.top_merchants.length?data.top_merchants.map((m,i)=><Box key={`${m.merchant}-${i}`} sx={{display:"flex",alignItems:"center",gap:2}}><Typography color="text.secondary" sx={{width:24}}>{i+1}</Typography><Typography sx={{flex:1}} fontWeight={650}>{m.merchant}</Typography><Typography>{money(m.amount)}</Typography></Box>):<Typography color="text.secondary">No accepted expenses in this range yet.</Typography>}</Stack></CardContent></Card>
  </Stack>;
}
