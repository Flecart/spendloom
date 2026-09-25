import { useEffect, useMemo, useState } from "react";
import { Alert, Box, Button, ButtonGroup, Card, CardContent, Chip, CircularProgress, Grid, MenuItem, Stack, TextField, Typography } from "@mui/material";
import { ArrowForwardRounded, ErrorOutlineRounded, ReceiptLongRounded, ReviewsRounded, TrendingDownRounded, TrendingUpRounded } from "@mui/icons-material";
import { Area, AreaChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, Dashboard, Expense, FinancialOverview, Scope, money } from "../api";
import { presetRange, rangeError, readSavedRange, saveRange, type RangePreset, type RangeState } from "./dashboardRange";

type RangeFiltersProps = {
  range: RangeState;
  onChange: (range: RangeState) => void;
};

function RangeFilters({ range, onChange }: RangeFiltersProps) {
  const presets: [RangePreset, string][] = [
    ["month", "This month"],
    ["3m", "3 months"],
    ["6m", "6 months"],
    ["12m", "12 months"],
    ["ytd", "Year to date"],
    ["all", "All time"],
  ];

  return <Card>
    <CardContent>
      <Stack spacing={1.5}>
        <ButtonGroup size="small" variant="outlined" sx={{ flexWrap: "wrap", justifyContent: "flex-start" }}>
          {presets.map(([preset, label]) =>
            <Button key={preset} variant={range.preset === preset ? "contained" : "outlined"} onClick={() => onChange(presetRange(preset, range))}>{label}</Button>
          )}
          <Button variant={range.preset === "custom" ? "contained" : "outlined"} onClick={() => onChange(presetRange("custom", range))}>Custom</Button>
        </ButtonGroup>
        <Box sx={{ display: "flex", gap: 1, flexWrap: "wrap", alignItems: "center" }}>
          <TextField size="small" label="From" type="date" value={range.date_from} slotProps={{ inputLabel: { shrink: true } }} onChange={event => onChange({ ...range, preset: "custom", date_from: event.target.value })} />
          <TextField size="small" label="To" type="date" value={range.date_to} slotProps={{ inputLabel: { shrink: true } }} onChange={event => onChange({ ...range, preset: "custom", date_to: event.target.value })} />
          <TextField size="small" select label="Scope" value={range.scope} onChange={event => onChange({ ...range, scope: event.target.value as "" | Scope })} sx={{ minWidth: 140 }}>
            <MenuItem value="">All scopes</MenuItem>
            <MenuItem value="personal">Personal</MenuItem>
            <MenuItem value="business">Business</MenuItem>
            <MenuItem value="unknown">Unknown</MenuItem>
          </TextField>
        </Box>
      </Stack>
    </CardContent>
  </Card>;
}

type DashboardCategory = Dashboard["by_category"][number];

function formatChartDate(value: string): string {
  return new Date(`${value}T12:00:00`).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function SpendingTrend({ data }: { data: Dashboard }) {
  const weekly = data.trend_granularity === "week";

  return (
    <Card>
      <CardContent>
        <Typography variant="h6">{weekly ? "Weekly" : "Daily"} spending</Typography>
        <Typography variant="body2" color="text.secondary">
          {formatChartDate(data.date_from)} – {formatChartDate(data.date_to)}
        </Typography>
        <Box sx={{ height: 290, mt: 2 }}>
          <ResponsiveContainer>
            <AreaChart data={data.by_period}>
              <defs>
                <linearGradient id="spend" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#7a365d" stopOpacity={0.35} />
                  <stop offset="95%" stopColor="#7a365d" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis
                dataKey="date"
                minTickGap={24}
                tickFormatter={(value) => formatChartDate(String(value))}
              />
              <YAxis tickFormatter={(value) => `€${value}`} />
              <Tooltip
                labelFormatter={(value) => `${weekly ? "Week of " : ""}${formatChartDate(String(value))}`}
                formatter={(value) => money(Number(value))}
              />
              <Area
                type="linear"
                dataKey="amount"
                stroke="#7a365d"
                strokeWidth={3}
                fill="url(#spend)"
              />
            </AreaChart>
          </ResponsiveContainer>
        </Box>
      </CardContent>
    </Card>
  );
}

function CategoryBreakdown({
  categories,
  selectedId,
  onSelect,
}: {
  categories: DashboardCategory[];
  selectedId: string | null;
  onSelect: (categoryId: string) => void;
}) {
  return (
    <Card sx={{ height: "100%" }}>
      <CardContent>
        <Typography variant="h6" fontWeight={750}>By category</Typography>
        {categories.length === 0 ? (
          <Box className="empty-state">Your category breakdown will appear here.</Box>
        ) : (
          <>
            <Box sx={{ height: 210 }}>
              <ResponsiveContainer>
                <PieChart>
                  <Pie data={categories} dataKey="amount" nameKey="name" innerRadius={55} outerRadius={85}>
                    {categories.map((category) => (
                      <Cell
                        key={category.id}
                        fill={category.color}
                        onClick={() => onSelect(category.id)}
                        style={{ cursor: "pointer" }}
                      />
                    ))}
                  </Pie>
                  <Tooltip formatter={(value) => money(Number(value))} />
                </PieChart>
              </ResponsiveContainer>
            </Box>
            <Stack spacing={1} sx={{ maxHeight: 240, overflowY: "auto" }}>
              {categories.map((category) => (
                <Button
                  key={category.id}
                  onClick={() => onSelect(category.id)}
                  variant={category.id === selectedId ? "contained" : "text"}
                  sx={{ justifyContent: "space-between", borderLeft: `5px solid ${category.color}` }}
                >
                  <span>{category.name}</span>
                  <span>{money(category.amount)}</span>
                </Button>
              ))}
            </Stack>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function CategoryTransactionsPanel({
  category,
  query,
}: {
  category: DashboardCategory;
  query: string;
}) {
  const [items, setItems] = useState<Expense[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let current = true;
    const params = new URLSearchParams(query);
    params.set("state", "accepted");
    params.set("category_id", category.id);
    params.set("limit", "1000");

    api<Expense[]>(`/api/expenses?${params}`)
      .then((expenses) => {
        if (current) {
          setItems(expenses);
        }
      })
      .catch((reason: Error) => {
        if (current) {
          setError(reason.message);
        }
      })
      .finally(() => {
        if (current) {
          setLoading(false);
        }
      });
    return () => {
      current = false;
    };
  }, [category.id, query]);

  return (
    <Card>
      <CardContent>
        <Typography variant="h6">{category.name} transactions</Typography>
        <Typography color="text.secondary">{money(category.amount)} in the selected range</Typography>
        {loading ? (
          <CircularProgress sx={{ mt: 2 }} />
        ) : error ? (
          <Alert severity="error" sx={{ mt: 2 }}>{error}</Alert>
        ) : items.length === 0 ? (
          <Typography sx={{ mt: 2 }}>No transactions found.</Typography>
        ) : (
          <Stack spacing={0.5} sx={{ mt: 2, maxHeight: 400, overflowY: "auto" }}>
            {items.map((expense) => (
              <Button
                key={expense.id}
                href={`/expenses/${expense.id}`}
                sx={{ display: "flex", justifyContent: "space-between", textAlign: "left" }}
              >
                <span>{expense.expense_date} · {expense.merchant || "Unknown merchant"}</span>
                <span>{money(expense.amount)}</span>
              </Button>
            ))}
          </Stack>
        )}
        {items.length === 1000 && (
          <Typography variant="caption">Showing the latest 1,000 transactions.</Typography>
        )}
      </CardContent>
    </Card>
  );
}

export default function DashboardPage({ onReview }: { onReview: () => void }) {
  const [range, setRange] = useState<RangeState>(readSavedRange);
  const [data, setData] = useState<Dashboard | null>(null);
  const [finance, setFinance] = useState<FinancialOverview | null>(null);
  const [selectedCategoryId, setSelectedCategoryId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const validationError = rangeError(range);
  const query = useMemo(() => {
    const params = new URLSearchParams({ date_from: range.date_from, date_to: range.date_to });
    if (range.scope) params.set("scope", range.scope);
    return params.toString();
  }, [range]);

  useEffect(() => {
    setError("");
    setData(null);
    setFinance(null);
    if (validationError) return;

    let current = true;
    saveRange(range);
    Promise.all([
      api<Dashboard>(`/api/dashboard?${query}`),
      api<FinancialOverview>(`/api/financial-overview?date_from=${range.date_from}&date_to=${range.date_to}`),
    ]).then(([dashboard, financial]) => {
      if (!current) return;
      setData(dashboard);
      setFinance(financial);
    }).catch((reason: Error) => {
      if (current) setError(reason.message);
    });
    return () => { current = false; };
  }, [query, range, validationError]);

  const filters = <RangeFilters range={range} onChange={setRange} />;
  const notice = validationError || error;
  if (notice || !data || !finance) {
    return <Stack spacing={3}>
      {filters}
      {notice && <Alert severity="error">{notice}</Alert>}
      {!notice && <Box sx={{ display: "grid", placeItems: "center", height: 300 }}><CircularProgress /></Box>}
    </Stack>;
  }
  const previous = Number(data.previous_range_total);
  const current = Number(data.range_total);
  const direction = current >= previous;
  const title = `${formatChartDate(data.date_from)} – ${formatChartDate(data.date_to)}`;
  const selectedCategory = data.by_category.find((category) => category.id === selectedCategoryId);
  const selectCategory = (categoryId: string) => {
    setSelectedCategoryId((currentId) => currentId === categoryId ? null : categoryId);
  };
  return <Stack spacing={3}>
    <Box><Typography className="eyebrow">Overview</Typography><Typography variant="h4" className="page-title">Your spending, in context</Typography><Typography color="text.secondary">Accepted expenses in <b>{title}</b>{range.scope?` · ${range.scope}`:""}.</Typography></Box>
    {filters}
    <Grid container spacing={2}>{[
      ["Income",money(finance.income_total),<TrendingUpRounded/>],
      ["Net cash flow",money(finance.net_cash_flow),Number(finance.net_cash_flow)>=0?<TrendingUpRounded/>:<TrendingDownRounded/>],
      ["Outstanding invoices",money(finance.outstanding_receivables),<ReceiptLongRounded/>],
      ["Due / overdue",`${finance.due_count} / ${finance.overdue_count}`,<ReviewsRounded/>],
    ].map(([label,value,icon])=><Grid key={String(label)} size={{xs:12,sm:6,lg:3}}><Card className="metric-card"><CardContent><Box sx={{color:"primary.main",mb:2}}>{icon}</Box><Typography variant="h5">{value}</Typography><Typography color="text.secondary">{label}</Typography></CardContent></Card></Grid>)}</Grid>
    {data.review_count>0&&<Alert severity="info" action={<Button onClick={onReview} endIcon={<ArrowForwardRounded/>}>Review now</Button>}>{data.review_count} receipt{data.review_count===1?"":"s"} need your attention in this range.</Alert>}
    <Grid container spacing={2}>{[
      ["Spent in selected range",money(data.range_total),direction?<TrendingUpRounded/>:<TrendingDownRounded/>],
      ["Previous equivalent range",money(data.previous_range_total),<TrendingDownRounded/>],
      ["Awaiting review",String(data.review_count),<ReviewsRounded/>],
      ["Receipts stored",String(data.receipt_count),<ReceiptLongRounded/>],
      ["Failed imports",String(data.failed_count),<ErrorOutlineRounded/>],
    ].map(([label,value,icon])=><Grid key={String(label)} size={{xs:12,sm:6,lg:label==="Spent in selected range"?4:2}}><Card className="metric-card"><CardContent><Box sx={{color:"primary.main",mb:2}}>{icon}</Box><Typography variant="h5">{value}</Typography><Typography color="text.secondary">{label}</Typography></CardContent></Card></Grid>)}</Grid>
    <Grid container spacing={2}>
      <Grid size={{ xs: 12, lg: 8 }}>
        <SpendingTrend data={data} />
      </Grid>
      <Grid size={{ xs: 12, lg: 4 }}>
        <CategoryBreakdown
          categories={data.by_category}
          selectedId={selectedCategoryId}
          onSelect={selectCategory}
        />
      </Grid>
    </Grid>
    {selectedCategory && (
      <CategoryTransactionsPanel
        key={`${selectedCategory.id}-${query}`}
        category={selectedCategory}
        query={query}
      />
    )}
    <Card><CardContent><Typography variant="h6" fontWeight={750} sx={{mb:2}}>Top merchants</Typography><Stack spacing={1.5}>{data.top_merchants.length?data.top_merchants.map((m,i)=><Box key={`${m.merchant}-${i}`} sx={{display:"flex",alignItems:"center",gap:2}}><Typography color="text.secondary" sx={{width:24}}>{i+1}</Typography><Typography sx={{flex:1}} fontWeight={650}>{m.merchant}</Typography><Typography>{money(m.amount)}</Typography></Box>):<Typography color="text.secondary">No accepted expenses in this range yet.</Typography>}</Stack></CardContent></Card>
  </Stack>;
}
