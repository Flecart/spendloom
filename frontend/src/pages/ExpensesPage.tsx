import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  Chip,
  CircularProgress,
  InputAdornment,
  MenuItem,
  Stack,
  TextField,
  Typography,
  useMediaQuery,
} from "@mui/material";
import { DownloadRounded, SearchRounded } from "@mui/icons-material";
import { DataGrid, GridColDef } from "@mui/x-data-grid";

import {
  api,
  Category,
  downloadReimbursementZip,
  Expense,
  Ingestion,
  money,
} from "../api";
import ExpenseEditor from "../components/ExpenseEditor";

interface ExpensesPageProps {
  reviewOnly?: boolean;
  onChanged?: () => void;
  initialExpenseId?: string;
}

const statusColors: Record<string, "default" | "success" | "warning" | "error" | "info"> = {
  accepted: "success",
  needs_review: "warning",
  duplicate: "error",
  queued: "info",
  processing: "info",
  failed: "error",
};

const processingStatuses = ["queued", "processing", "failed"];

const expenseColumns: GridColDef<Expense>[] = [
  { field: "expense_date", headerName: "Date", width: 115 },
  { field: "merchant", headerName: "Merchant", flex: 1, minWidth: 170 },
  { field: "category_name", headerName: "Category", width: 150 },
  { field: "scope", headerName: "Scope", width: 110 },
  { field: "payment_method_name", headerName: "Payment", width: 140 },
  {
    field: "amount",
    headerName: "Amount",
    width: 125,
    align: "right",
    headerAlign: "right",
    valueFormatter: (value) => money(value),
  },
  {
    field: "status",
    headerName: "Status",
    width: 145,
    renderCell: (params) => (
      <Chip
        size="small"
        color={statusColors[params.value] || "default"}
        label={String(params.value).replace("_", " ")}
      />
    ),
  },
];

export default function ExpensesPage({
  reviewOnly = false,
  onChanged,
  initialExpenseId,
}: ExpensesPageProps) {
  const initialOpened = useRef(false);
  const mobile = useMediaQuery("(max-width:760px)");

  const [items, setItems] = useState<Expense[]>([]);
  const [ingestions, setIngestions] = useState<Ingestion[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [selectedExpense, setSelectedExpense] = useState<Expense | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [scope, setScope] = useState("");
  const [category, setCategory] = useState("");

  const loadExpenses = () => {
    setLoading(true);

    const parameters = new URLSearchParams();
    if (reviewOnly) parameters.set("state", "review");
    if (search) parameters.set("search", search);
    if (scope) parameters.set("scope", scope);
    if (category) parameters.set("category_id", category);

    Promise.all([
      api<Expense[]>(`/api/expenses?${parameters}`),
      api<Category[]>("/api/categories"),
      reviewOnly ? api<Ingestion[]>("/api/ingestions?limit=100") : Promise.resolve([]),
    ])
      .then(([loadedExpenses, loadedCategories, loadedIngestions]) => {
        setItems(loadedExpenses);
        setCategories(loadedCategories);
        setIngestions(loadedIngestions);
        setSelectedIds((current) => new Set(
          [...current].filter((id) => loadedExpenses.some((expense) => expense.id === id)),
        ));

        if (initialExpenseId && !initialOpened.current) {
          initialOpened.current = true;
          const matchingExpense = loadedExpenses.find((expense) => expense.id === initialExpenseId);
          if (matchingExpense) {
            setSelectedExpense(matchingExpense);
          } else {
            api<Expense>(`/api/expenses/${initialExpenseId}`)
              .then(setSelectedExpense)
              .catch(() => setError("The linked expense was not found."));
          }
        }

        setError("");
      })
      .catch((loadError: Error) => setError(loadError.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    const timer = setTimeout(loadExpenses, 250);
    return () => clearTimeout(timer);
  }, [reviewOnly, search, scope, category]);

  const handleChanged = () => {
    loadExpenses();
    onChanged?.();
  };

  const selectedExpenses = items.filter((item) => selectedIds.has(item.id));
  const selectedTotal = selectedExpenses.reduce(
    (total, item) => total + Number(item.amount || 0),
    0,
  );

  const toggleSelection = (expense: Expense) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(expense.id)) {
        next.delete(expense.id);
      } else {
        next.add(expense.id);
      }
      return next;
    });
  };

  const downloadSelectedExpenses = async () => {
    setDownloading(true);
    setError("");

    try {
      await downloadReimbursementZip(selectedExpenses.map((expense) => expense.id));
    } catch (downloadError) {
      setError(
        downloadError instanceof Error
          ? downloadError.message
          : "Unable to create reimbursement ZIP.",
      );
    } finally {
      setDownloading(false);
    }
  };

  const reviewIngestions = ingestions.filter((ingestion) => processingStatuses.includes(ingestion.status));

  return (
    <Stack spacing={3}>
      <Box
        sx={{
          display: "flex",
          justifyContent: "space-between",
          gap: 2,
          alignItems: "end",
          flexWrap: "wrap",
        }}
      >
        <Box>
          <Typography className="eyebrow">
            {reviewOnly ? "Needs attention" : "Complete ledger"}
          </Typography>
          <Typography variant="h4" className="page-title">
            {reviewOnly ? "Review inbox" : "Expenses"}
          </Typography>
        </Box>
        <Stack direction="row" spacing={1} flexWrap="wrap">
          {selectedExpenses.length > 0 && (
            <Button
              onClick={downloadSelectedExpenses}
              disabled={downloading}
              startIcon={<DownloadRounded />}
              variant="contained"
            >
              {downloading
                ? "Preparing ZIP…"
                : `Download reimbursement ZIP (${selectedExpenses.length} · ${money(selectedTotal)})`}
            </Button>
          )}
          {!reviewOnly && (
            <Button
              href="/api/exports/expenses.csv?extended=true"
              startIcon={<DownloadRounded />}
              variant="outlined"
            >
              Export CSV
            </Button>
          )}
        </Stack>
      </Box>

      <Card>
        <CardContent
          sx={{
            display: "grid",
            gridTemplateColumns: { xs: "1fr", md: "2fr 1fr 1fr" },
            gap: 1.5,
          }}
        >
          <TextField
            size="small"
            placeholder="Search merchant or memo"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <SearchRounded />
                </InputAdornment>
              ),
            }}
          />
          <TextField
            select
            size="small"
            label="Scope"
            value={scope}
            onChange={(event) => setScope(event.target.value)}
          >
            <MenuItem value="">All scopes</MenuItem>
            {["personal", "business", "unknown"].map((value) => (
              <MenuItem key={value} value={value}>{value}</MenuItem>
            ))}
          </TextField>
          <TextField
            select
            size="small"
            label="Category"
            value={category}
            onChange={(event) => setCategory(event.target.value)}
          >
            <MenuItem value="">All categories</MenuItem>
            {categories.map((item) => (
              <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>
            ))}
          </TextField>
        </CardContent>
      </Card>

      {error && <Alert severity="error">{error}</Alert>}

      {reviewOnly && reviewIngestions.map((ingestion) => (
        <Alert key={ingestion.id} severity={ingestion.status === "failed" ? "error" : "info"}>
          <strong>{ingestion.status === "failed" ? "Import failed" : "Receipt processing"}</strong>
          {` · ${ingestion.source} · ${new Date(ingestion.received_at).toLocaleString()} · ${ingestion.id.slice(0, 8)}`}
          {ingestion.error_message ? ` — ${ingestion.error_message}` : ""}
        </Alert>
      ))}

      {loading ? (
        <Box sx={{ display: "grid", placeItems: "center", height: 280 }}>
          <CircularProgress />
        </Box>
      ) : items.length === 0 ? (
        <Card>
          <Box className="empty-state">
            <Typography variant="h6">
              {reviewOnly ? "No receipts need review" : "No expenses found"}
            </Typography>
            <Typography>
              {reviewOnly && ingestions.some((item) => ["queued", "processing"].includes(item.status))
                ? "Your newest receipt is still processing."
                : "New receipts will appear here after processing."}
            </Typography>
          </Box>
        </Card>
      ) : mobile ? (
        <Stack spacing={1.5}>
          {items.map((expense) => (
            <Card key={expense.id} onClick={() => setSelectedExpense(expense)}>
              <CardContent
                sx={{
                  display: "flex",
                  justifyContent: "space-between",
                  gap: 1,
                  alignItems: "start",
                }}
              >
                <Checkbox
                  aria-label={`Select ${expense.merchant || "expense"} for reimbursement`}
                  checked={selectedIds.has(expense.id)}
                  disabled={!expense.receipt_id}
                  onClick={(event) => event.stopPropagation()}
                  onChange={() => toggleSelection(expense)}
                />
                <Box sx={{ flex: 1 }}>
                  <Typography fontWeight={750}>{expense.merchant || "Unknown merchant"}</Typography>
                  <Typography variant="body2" color="text.secondary">
                    {expense.expense_date || "No date"} · {expense.category_name || "Uncategorised"}
                  </Typography>
                  <Chip
                    size="small"
                    sx={{ mt: 1 }}
                    color={statusColors[expense.status] || "default"}
                    label={expense.status.replace("_", " ")}
                  />
                </Box>
                <Typography fontWeight={750}>{money(expense.amount)}</Typography>
              </CardContent>
            </Card>
          ))}
        </Stack>
      ) : (
        <Card>
          <Box sx={{ height: "min(68vh,720px)" }}>
            <DataGrid
              rows={items}
              columns={expenseColumns}
              checkboxSelection
              isRowSelectable={(params) => Boolean((params.row as Expense).receipt_id)}
              rowSelectionModel={{ type: "include", ids: selectedIds }}
              onRowSelectionModelChange={(model) => {
                setSelectedIds(new Set(Array.from(model.ids, String)));
              }}
              disableRowSelectionOnClick
              onRowClick={(params) => setSelectedExpense(params.row as Expense)}
              initialState={{ pagination: { paginationModel: { pageSize: 25, page: 0 } } }}
              pageSizeOptions={[25, 50, 100]}
              sx={{ border: 0, "& .MuiDataGrid-row": { cursor: "pointer" } }}
            />
          </Box>
        </Card>
      )}

      <ExpenseEditor
        expense={selectedExpense}
        open={Boolean(selectedExpense)}
        onClose={() => setSelectedExpense(null)}
        onChanged={handleChanged}
      />
    </Stack>
  );
}
