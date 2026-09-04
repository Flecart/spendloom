import { FormEvent, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { AddRounded, CheckRounded, ScheduleRounded } from "@mui/icons-material";

import {
  api,
  Category,
  Contract,
  IncomeKind,
  money,
  PaymentMethod,
  RecurrenceFrequency,
  RecurringEntryType,
  RecurringItem,
  RecurringOccurrence,
  Scope,
} from "../api";
import DocumentUpload from "../components/DocumentUpload";

interface RecurringForm {
  name: string;
  entry_type: RecurringEntryType;
  counterparty: string;
  expected_amount: string;
  currency: string;
  frequency: RecurrenceFrequency;
  start_date: string;
  end_date: string;
  reminder_days_before: string;
  category_id: string;
  payment_method_id: string;
  scope: Scope;
  income_kind: IncomeKind;
  contract_id: string;
}

function initialForm(): RecurringForm {
  return {
    name: "",
    entry_type: "expense",
    counterparty: "",
    expected_amount: "",
    currency: "EUR",
    frequency: "monthly",
    start_date: new Date().toISOString().slice(0, 10),
    end_date: "",
    reminder_days_before: "3",
    category_id: "",
    payment_method_id: "",
    scope: "personal",
    income_kind: "contract",
    contract_id: "",
  };
}

export default function RecurringPage() {
  const [items, setItems] = useState<RecurringItem[]>([]);
  const [occurrences, setOccurrences] = useState<RecurringOccurrence[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [methods, setMethods] = useState<PaymentMethod[]>([]);
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [form, setForm] = useState<RecurringForm>(initialForm);
  const [error, setError] = useState("");

  const load = (): Promise<void> => Promise.all([
    api<RecurringItem[]>("/api/recurring-items"),
    api<RecurringOccurrence[]>("/api/recurring-occurrences"),
    api<Category[]>("/api/categories"),
    api<PaymentMethod[]>("/api/payment-methods"),
    api<Contract[]>("/api/contracts"),
  ])
    .then(([loadedItems, loadedOccurrences, loadedCategories, loadedMethods, loadedContracts]) => {
      setItems(loadedItems);
      setOccurrences(loadedOccurrences);
      setCategories(loadedCategories);
      setMethods(loadedMethods);
      setContracts(loadedContracts);
    })
    .catch((loadError: Error) => setError(loadError.message));

  useEffect(() => {
    load();
  }, []);

  const submit = async (event: FormEvent): Promise<void> => {
    event.preventDefault();
    try {
      await api<RecurringItem>("/api/recurring-items", {
        method: "POST",
        body: JSON.stringify({
          ...form,
          expected_amount: form.expected_amount || null,
          end_date: form.end_date || null,
          reminder_days_before: Number(form.reminder_days_before),
          category_id: form.entry_type === "expense" ? form.category_id || null : null,
          payment_method_id: form.entry_type === "expense" ? form.payment_method_id || null : null,
          income_kind: form.entry_type === "income" ? form.income_kind : null,
          contract_id: form.contract_id || null,
        }),
      });
      setForm(initialForm());
      await load();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Could not add schedule");
    }
  };

  const complete = async (occurrence: RecurringOccurrence): Promise<void> => {
    let amount = occurrence.expected_amount;
    if (!amount) {
      amount = window.prompt(`Actual amount in ${occurrence.currency}`) || "";
    }
    if (!amount) {
      return;
    }
    try {
      await api(`/api/recurring-occurrences/${occurrence.id}/complete`, {
        method: "POST",
        body: JSON.stringify({ amount }),
      });
      await load();
    } catch (completeError) {
      setError(completeError instanceof Error ? completeError.message : "Could not record occurrence");
    }
  };

  const skip = async (occurrence: RecurringOccurrence): Promise<void> => {
    try {
      await api(`/api/recurring-occurrences/${occurrence.id}/skip`, { method: "POST" });
      await load();
    } catch (skipError) {
      setError(skipError instanceof Error ? skipError.message : "Could not skip occurrence");
    }
  };

  return (
    <Stack spacing={3}>
      <Box>
        <Typography className="eyebrow">Expected cash flow</Typography>
        <Typography variant="h4" className="page-title">Recurring</Typography>
        <Typography color="text.secondary">
          Schedules create reminders, not financial transactions, until you confirm them.
        </Typography>
      </Box>
      {error && <Alert severity="error" onClose={() => setError("")}>{error}</Alert>}
      <Card>
        <CardContent>
          <Typography variant="h6" fontWeight={750} sx={{ mb: 2 }}>Add schedule</Typography>
          <Box
            component="form"
            onSubmit={submit}
            sx={{
              display: "grid",
              gridTemplateColumns: { xs: "1fr", md: "repeat(4, 1fr)" },
              gap: 1.5,
            }}
          >
            <TextField
              select
              label="Type"
              value={form.entry_type}
              onChange={(event) => setForm({
                ...form,
                entry_type: event.target.value as RecurringEntryType,
              })}
            >
              <MenuItem value="expense">Expense</MenuItem>
              <MenuItem value="income">Income</MenuItem>
            </TextField>
            <TextField
              required
              label="Name"
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
            />
            <TextField
              required
              label={form.entry_type === "expense" ? "Merchant" : "Payer"}
              value={form.counterparty}
              onChange={(event) => setForm({ ...form, counterparty: event.target.value })}
            />
            <TextField
              type="number"
              label="Expected amount (optional)"
              inputProps={{ min: 0.01, step: 0.01 }}
              value={form.expected_amount}
              onChange={(event) => setForm({ ...form, expected_amount: event.target.value })}
            />
            <TextField
              required
              label="Currency"
              value={form.currency}
              inputProps={{ maxLength: 3 }}
              onChange={(event) => setForm({ ...form, currency: event.target.value.toUpperCase() })}
            />
            <TextField
              select
              label="Frequency"
              value={form.frequency}
              onChange={(event) => setForm({
                ...form,
                frequency: event.target.value as RecurrenceFrequency,
              })}
            >
              {(["weekly", "monthly", "quarterly", "yearly"] as RecurrenceFrequency[]).map((frequency) => (
                <MenuItem key={frequency} value={frequency}>{frequency}</MenuItem>
              ))}
            </TextField>
            <TextField
              required
              type="date"
              label="First due date"
              value={form.start_date}
              slotProps={{ inputLabel: { shrink: true } }}
              onChange={(event) => setForm({ ...form, start_date: event.target.value })}
            />
            <TextField
              type="date"
              label="End date"
              value={form.end_date}
              slotProps={{ inputLabel: { shrink: true } }}
              onChange={(event) => setForm({ ...form, end_date: event.target.value })}
            />
            <TextField
              type="number"
              label="Remind days before"
              inputProps={{ min: 0, max: 365 }}
              value={form.reminder_days_before}
              onChange={(event) => setForm({ ...form, reminder_days_before: event.target.value })}
            />
            {form.entry_type === "expense" && (
              <TextField
                select
                label="Category"
                value={form.category_id}
                onChange={(event) => setForm({ ...form, category_id: event.target.value })}
              >
                <MenuItem value="">No category</MenuItem>
                {categories.map((category) => (
                  <MenuItem key={category.id} value={category.id}>{category.name}</MenuItem>
                ))}
              </TextField>
            )}
            {form.entry_type === "expense" && (
              <TextField
                select
                label="Payment method"
                value={form.payment_method_id}
                onChange={(event) => setForm({ ...form, payment_method_id: event.target.value })}
              >
                <MenuItem value="">Default</MenuItem>
                {methods.map((method) => (
                  <MenuItem key={method.id} value={method.id}>{method.name}</MenuItem>
                ))}
              </TextField>
            )}
            {form.entry_type === "income" && (
              <TextField
                select
                label="Income kind"
                value={form.income_kind}
                onChange={(event) => setForm({
                  ...form,
                  income_kind: event.target.value as IncomeKind,
                })}
              >
                {(["salary", "contract", "rental", "interest", "refund", "other"] as IncomeKind[]).map((kind) => (
                  <MenuItem key={kind} value={kind}>{kind}</MenuItem>
                ))}
              </TextField>
            )}
            <TextField
              select
              label="Contract"
              value={form.contract_id}
              onChange={(event) => setForm({ ...form, contract_id: event.target.value })}
            >
              <MenuItem value="">No contract</MenuItem>
              {contracts.map((contract) => (
                <MenuItem key={contract.id} value={contract.id}>{contract.title}</MenuItem>
              ))}
            </TextField>
            <Button type="submit" variant="contained" startIcon={<AddRounded />}>
              Add schedule
            </Button>
          </Box>
        </CardContent>
      </Card>
      <Card>
        <CardContent>
          <Typography variant="h6" fontWeight={750} sx={{ mb: 2 }}>Due and upcoming</Typography>
          <Stack spacing={1.5}>
            {occurrences.map((occurrence) => (
              <Box
                key={occurrence.id}
                sx={{ display: "flex", alignItems: "center", gap: 1.5, flexWrap: "wrap" }}
              >
                <ScheduleRounded color={occurrence.timing === "overdue" ? "error" : "primary"} />
                <Box sx={{ flex: 1, minWidth: 210 }}>
                  <Typography fontWeight={700}>{occurrence.recurring_item_name}</Typography>
                  <Typography variant="body2" color="text.secondary">
                    {occurrence.counterparty} · {occurrence.due_date}
                  </Typography>
                </Box>
                <Chip
                  color={occurrence.timing === "overdue" ? "error" : "default"}
                  label={occurrence.timing}
                />
                <Typography>
                  {occurrence.expected_amount
                    ? money(occurrence.expected_amount, occurrence.currency)
                    : "Variable"}
                </Typography>
                <DocumentUpload
                  targetType="occurrence"
                  targetId={occurrence.id}
                  onUploaded={() => undefined}
                  onError={setError}
                />
                <Button startIcon={<CheckRounded />} onClick={() => complete(occurrence)}>
                  Record
                </Button>
                <Button color="inherit" onClick={() => skip(occurrence)}>Skip</Button>
              </Box>
            ))}
            {!occurrences.length && <Box className="empty-state">Nothing is currently due.</Box>}
          </Stack>
        </CardContent>
      </Card>
      <Card>
        <CardContent>
          <Typography variant="h6" fontWeight={750} sx={{ mb: 2 }}>Schedules</Typography>
          <Stack spacing={1}>
            {items.map((item) => (
              <Box key={item.id} sx={{ display: "flex", justifyContent: "space-between", gap: 2 }}>
                <Typography>{item.name} · {item.frequency}</Typography>
                <Typography color="text.secondary">Next: {item.next_due_date || "none"}</Typography>
              </Box>
            ))}
          </Stack>
        </CardContent>
      </Card>
    </Stack>
  );
}
