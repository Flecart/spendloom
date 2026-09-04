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
import { AddRounded } from "@mui/icons-material";

import {
  api,
  Contract,
  Income,
  IncomeKind,
  money,
  SupportingDocument,
} from "../api";
import DocumentUpload from "../components/DocumentUpload";

interface IncomeForm {
  received_date: string;
  payer: string;
  kind: IncomeKind;
  original_amount: string;
  original_currency: string;
  contract_id: string;
  memo: string;
}

function emptyForm(): IncomeForm {
  return {
    received_date: new Date().toISOString().slice(0, 10),
    payer: "",
    kind: "other",
    original_amount: "",
    original_currency: "EUR",
    contract_id: "",
    memo: "",
  };
}

export default function IncomePage() {
  const [items, setItems] = useState<Income[]>([]);
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [form, setForm] = useState<IncomeForm>(emptyForm);
  const [error, setError] = useState("");

  const load = (): Promise<void> => Promise.all([
    api<Income[]>("/api/income"),
    api<Contract[]>("/api/contracts"),
  ])
    .then(([income, loadedContracts]) => {
      setItems(income);
      setContracts(loadedContracts);
    })
    .catch((loadError: Error) => setError(loadError.message));

  useEffect(() => {
    load();
  }, []);

  const submit = async (event: FormEvent): Promise<void> => {
    event.preventDefault();
    setError("");
    try {
      await api<Income>("/api/income", {
        method: "POST",
        body: JSON.stringify({
          ...form,
          contract_id: form.contract_id || null,
        }),
      });
      setForm(emptyForm());
      await load();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Could not record income");
    }
  };

  const documentAdded = (incomeId: string, document: SupportingDocument): void => {
    setItems((current) => current.map((item) => (
      item.id === incomeId
        ? {
          ...item,
          documents: [...item.documents, document],
          document_count: item.document_count + 1,
        }
        : item
    )));
  };

  return (
    <Stack spacing={3}>
      <Box>
        <Typography className="eyebrow">Money received</Typography>
        <Typography variant="h4" className="page-title">Income</Typography>
        <Typography color="text.secondary">
          Record earnings and connect them to contracts and invoice payments.
        </Typography>
      </Box>
      {error && <Alert severity="error" onClose={() => setError("")}>{error}</Alert>}
      <Card>
        <CardContent>
          <Box
            component="form"
            onSubmit={submit}
            sx={{
              display: "grid",
              gridTemplateColumns: { xs: "1fr", md: "1fr 2fr 1fr 1fr 1fr" },
              gap: 1.5,
            }}
          >
            <TextField
              required
              type="date"
              label="Received"
              value={form.received_date}
              slotProps={{ inputLabel: { shrink: true } }}
              onChange={(event) => setForm({ ...form, received_date: event.target.value })}
            />
            <TextField
              required
              label="Payer"
              value={form.payer}
              onChange={(event) => setForm({ ...form, payer: event.target.value })}
            />
            <TextField
              select
              label="Kind"
              value={form.kind}
              onChange={(event) => setForm({ ...form, kind: event.target.value as IncomeKind })}
            >
              {(["salary", "contract", "rental", "interest", "refund", "other"] as IncomeKind[]).map((kind) => (
                <MenuItem key={kind} value={kind}>{kind}</MenuItem>
              ))}
            </TextField>
            <TextField
              required
              type="number"
              label="Amount"
              inputProps={{ min: 0.01, step: 0.01 }}
              value={form.original_amount}
              onChange={(event) => setForm({ ...form, original_amount: event.target.value })}
            />
            <TextField
              required
              label="Currency"
              inputProps={{ maxLength: 3 }}
              value={form.original_currency}
              onChange={(event) => setForm({
                ...form,
                original_currency: event.target.value.toUpperCase(),
              })}
            />
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
            <TextField
              label="Memo"
              value={form.memo}
              onChange={(event) => setForm({ ...form, memo: event.target.value })}
              sx={{ gridColumn: { md: "span 3" } }}
            />
            <Button type="submit" variant="contained" startIcon={<AddRounded />}>
              Record income
            </Button>
          </Box>
        </CardContent>
      </Card>
      <Stack spacing={1.5}>
        {items.map((item) => (
          <Card key={item.id}>
            <CardContent>
              <Box sx={{ display: "flex", gap: 2, alignItems: "center", flexWrap: "wrap" }}>
                <Box sx={{ flex: 1, minWidth: 220 }}>
                  <Typography fontWeight={750}>{item.payer}</Typography>
                  <Typography variant="body2" color="text.secondary">
                    {item.received_date} · {item.kind}
                    {item.contract_title ? ` · ${item.contract_title}` : ""}
                  </Typography>
                </Box>
                <Chip label={money(item.amount)} color="success" />
                {Number(item.allocated_amount) > 0 && (
                  <Chip label={`${money(item.allocated_amount, item.original_currency)} allocated`} />
                )}
                <DocumentUpload
                  targetType="income"
                  targetId={item.id}
                  onUploaded={(document) => documentAdded(item.id, document)}
                  onError={setError}
                />
              </Box>
              {item.documents.length > 0 && (
                <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
                  {item.documents.map((document) => (
                    <Button key={document.id} size="small" href={document.file_url}>
                      {document.filename}
                    </Button>
                  ))}
                </Stack>
              )}
            </CardContent>
          </Card>
        ))}
        {!items.length && <Box className="empty-state">No income has been recorded yet.</Box>}
      </Stack>
    </Stack>
  );
}
