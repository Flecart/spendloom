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
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import { AddRounded } from "@mui/icons-material";

import {
  api,
  Contract,
  Income,
  Invoice,
  money,
  SupportingDocument,
} from "../api";
import DocumentUpload from "../components/DocumentUpload";

interface ContractForm {
  title: string;
  counterparty: string;
  reference: string;
  start_date: string;
  end_date: string;
  status: Contract["status"];
  notes: string;
}

interface InvoiceForm {
  reference: string;
  client: string;
  contract_id: string;
  issue_date: string;
  due_date: string;
  currency: string;
  subtotal: string;
  tax_amount: string;
  total: string;
  memo: string;
}

const today = (): string => new Date().toISOString().slice(0, 10);

function newContract(): ContractForm {
  return {
    title: "",
    counterparty: "",
    reference: "",
    start_date: "",
    end_date: "",
    status: "active",
    notes: "",
  };
}

function newInvoice(): InvoiceForm {
  return {
    reference: "",
    client: "",
    contract_id: "",
    issue_date: today(),
    due_date: today(),
    currency: "EUR",
    subtotal: "",
    tax_amount: "0",
    total: "",
    memo: "",
  };
}

export default function ContractsPage() {
  const [tab, setTab] = useState(0);
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [income, setIncome] = useState<Income[]>([]);
  const [contractForm, setContractForm] = useState<ContractForm>(newContract);
  const [invoiceForm, setInvoiceForm] = useState<InvoiceForm>(newInvoice);
  const [allocationIncome, setAllocationIncome] = useState<Record<string, string>>({});
  const [allocationAmount, setAllocationAmount] = useState<Record<string, string>>({});
  const [error, setError] = useState("");

  const load = (): Promise<void> => Promise.all([
    api<Contract[]>("/api/contracts"),
    api<Invoice[]>("/api/invoices"),
    api<Income[]>("/api/income"),
  ])
    .then(([loadedContracts, loadedInvoices, loadedIncome]) => {
      setContracts(loadedContracts);
      setInvoices(loadedInvoices);
      setIncome(loadedIncome);
    })
    .catch((loadError: Error) => setError(loadError.message));

  useEffect(() => {
    load();
  }, []);

  const submitContract = async (event: FormEvent): Promise<void> => {
    event.preventDefault();
    try {
      await api<Contract>("/api/contracts", {
        method: "POST",
        body: JSON.stringify({
          ...contractForm,
          reference: contractForm.reference || null,
          start_date: contractForm.start_date || null,
          end_date: contractForm.end_date || null,
        }),
      });
      setContractForm(newContract());
      await load();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Could not add contract");
    }
  };

  const submitInvoice = async (event: FormEvent): Promise<void> => {
    event.preventDefault();
    try {
      await api<Invoice>("/api/invoices", {
        method: "POST",
        body: JSON.stringify({
          ...invoiceForm,
          contract_id: invoiceForm.contract_id || null,
        }),
      });
      setInvoiceForm(newInvoice());
      await load();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Could not add invoice");
    }
  };

  const allocate = async (invoice: Invoice): Promise<void> => {
    const incomeId = allocationIncome[invoice.id];
    const amount = allocationAmount[invoice.id];
    if (!incomeId || !amount) {
      setError("Choose an income entry and allocation amount");
      return;
    }
    try {
      await api(`/api/invoices/${invoice.id}/allocations`, {
        method: "POST",
        body: JSON.stringify({ income_id: incomeId, amount }),
      });
      setAllocationAmount({ ...allocationAmount, [invoice.id]: "" });
      await load();
    } catch (allocationError) {
      setError(allocationError instanceof Error ? allocationError.message : "Allocation failed");
    }
  };

  const documentAdded = (
    target: "contract" | "invoice",
    targetId: string,
    document: SupportingDocument,
  ): void => {
    if (target === "contract") {
      setContracts((current) => current.map((item) => (
        item.id === targetId
          ? { ...item, documents: [...item.documents, document], document_count: item.document_count + 1 }
          : item
      )));
    } else {
      setInvoices((current) => current.map((item) => (
        item.id === targetId
          ? { ...item, documents: [...item.documents, document], document_count: item.document_count + 1 }
          : item
      )));
    }
  };

  return (
    <Stack spacing={3}>
      <Box>
        <Typography className="eyebrow">Agreements and receivables</Typography>
        <Typography variant="h4" className="page-title">Contracts</Typography>
      </Box>
      {error && <Alert severity="error" onClose={() => setError("")}>{error}</Alert>}
      <Card>
        <Tabs value={tab} onChange={(_event, value: number) => setTab(value)}>
          <Tab label="Contracts" />
          <Tab label="Invoices" />
        </Tabs>
      </Card>
      {tab === 0 && (
        <>
          <Card>
            <CardContent>
              <Box
                component="form"
                onSubmit={submitContract}
                sx={{
                  display: "grid",
                  gridTemplateColumns: { xs: "1fr", md: "repeat(4, 1fr)" },
                  gap: 1.5,
                }}
              >
                <TextField
                  required
                  label="Contract title"
                  value={contractForm.title}
                  onChange={(event) => setContractForm({ ...contractForm, title: event.target.value })}
                />
                <TextField
                  required
                  label="Counterparty"
                  value={contractForm.counterparty}
                  onChange={(event) => setContractForm({ ...contractForm, counterparty: event.target.value })}
                />
                <TextField
                  label="Reference"
                  value={contractForm.reference}
                  onChange={(event) => setContractForm({ ...contractForm, reference: event.target.value })}
                />
                <TextField
                  select
                  label="Status"
                  value={contractForm.status}
                  onChange={(event) => setContractForm({
                    ...contractForm,
                    status: event.target.value as Contract["status"],
                  })}
                >
                  {(["draft", "active", "ended", "cancelled"] as Contract["status"][]).map((status) => (
                    <MenuItem key={status} value={status}>{status}</MenuItem>
                  ))}
                </TextField>
                <TextField
                  type="date"
                  label="Start date"
                  value={contractForm.start_date}
                  slotProps={{ inputLabel: { shrink: true } }}
                  onChange={(event) => setContractForm({ ...contractForm, start_date: event.target.value })}
                />
                <TextField
                  type="date"
                  label="End date"
                  value={contractForm.end_date}
                  slotProps={{ inputLabel: { shrink: true } }}
                  onChange={(event) => setContractForm({ ...contractForm, end_date: event.target.value })}
                />
                <TextField
                  label="Notes"
                  value={contractForm.notes}
                  onChange={(event) => setContractForm({ ...contractForm, notes: event.target.value })}
                  sx={{ gridColumn: { md: "span 2" } }}
                />
                <Button type="submit" variant="contained" startIcon={<AddRounded />}>
                  Add contract
                </Button>
              </Box>
            </CardContent>
          </Card>
          <Stack spacing={1.5}>
            {contracts.map((contract) => (
              <Card key={contract.id}>
                <CardContent>
                  <Box sx={{ display: "flex", gap: 2, alignItems: "center", flexWrap: "wrap" }}>
                    <Box sx={{ flex: 1 }}>
                      <Typography fontWeight={750}>{contract.title}</Typography>
                      <Typography variant="body2" color="text.secondary">
                        {contract.counterparty}{contract.reference ? ` · ${contract.reference}` : ""}
                      </Typography>
                    </Box>
                    <Chip label={contract.status} />
                    <DocumentUpload
                      targetType="contract"
                      targetId={contract.id}
                      onUploaded={(document) => documentAdded("contract", contract.id, document)}
                      onError={setError}
                    />
                  </Box>
                  {contract.documents.map((document) => (
                    <Button key={document.id} size="small" href={document.file_url}>
                      {document.filename}
                    </Button>
                  ))}
                </CardContent>
              </Card>
            ))}
          </Stack>
        </>
      )}
      {tab === 1 && (
        <>
          <Card>
            <CardContent>
              <Box
                component="form"
                onSubmit={submitInvoice}
                sx={{
                  display: "grid",
                  gridTemplateColumns: { xs: "1fr", md: "repeat(4, 1fr)" },
                  gap: 1.5,
                }}
              >
                <TextField
                  required
                  label="Invoice reference"
                  value={invoiceForm.reference}
                  onChange={(event) => setInvoiceForm({ ...invoiceForm, reference: event.target.value })}
                />
                <TextField
                  required
                  label="Client"
                  value={invoiceForm.client}
                  onChange={(event) => setInvoiceForm({ ...invoiceForm, client: event.target.value })}
                />
                <TextField
                  select
                  label="Contract"
                  value={invoiceForm.contract_id}
                  onChange={(event) => setInvoiceForm({ ...invoiceForm, contract_id: event.target.value })}
                >
                  <MenuItem value="">No contract</MenuItem>
                  {contracts.map((contract) => (
                    <MenuItem key={contract.id} value={contract.id}>{contract.title}</MenuItem>
                  ))}
                </TextField>
                <TextField
                  required
                  label="Currency"
                  value={invoiceForm.currency}
                  inputProps={{ maxLength: 3 }}
                  onChange={(event) => setInvoiceForm({ ...invoiceForm, currency: event.target.value.toUpperCase() })}
                />
                <TextField
                  required
                  type="date"
                  label="Issued"
                  value={invoiceForm.issue_date}
                  slotProps={{ inputLabel: { shrink: true } }}
                  onChange={(event) => setInvoiceForm({ ...invoiceForm, issue_date: event.target.value })}
                />
                <TextField
                  required
                  type="date"
                  label="Due"
                  value={invoiceForm.due_date}
                  slotProps={{ inputLabel: { shrink: true } }}
                  onChange={(event) => setInvoiceForm({ ...invoiceForm, due_date: event.target.value })}
                />
                <TextField
                  required
                  type="number"
                  label="Subtotal"
                  value={invoiceForm.subtotal}
                  onChange={(event) => setInvoiceForm({ ...invoiceForm, subtotal: event.target.value })}
                />
                <TextField
                  required
                  type="number"
                  label="Tax amount"
                  value={invoiceForm.tax_amount}
                  onChange={(event) => setInvoiceForm({ ...invoiceForm, tax_amount: event.target.value })}
                />
                <TextField
                  required
                  type="number"
                  label="Total"
                  value={invoiceForm.total}
                  onChange={(event) => setInvoiceForm({ ...invoiceForm, total: event.target.value })}
                />
                <TextField
                  label="Memo"
                  value={invoiceForm.memo}
                  onChange={(event) => setInvoiceForm({ ...invoiceForm, memo: event.target.value })}
                  sx={{ gridColumn: { md: "span 2" } }}
                />
                <Button type="submit" variant="contained" startIcon={<AddRounded />}>
                  Add invoice
                </Button>
              </Box>
            </CardContent>
          </Card>
          <Stack spacing={1.5}>
            {invoices.map((invoice) => (
              <Card key={invoice.id}>
                <CardContent>
                  <Box sx={{ display: "flex", gap: 2, alignItems: "center", flexWrap: "wrap" }}>
                    <Box sx={{ flex: 1, minWidth: 220 }}>
                      <Typography fontWeight={750}>{invoice.reference} · {invoice.client}</Typography>
                      <Typography variant="body2" color="text.secondary">
                        Due {invoice.due_date} · Outstanding {money(invoice.outstanding_amount, invoice.currency)}
                      </Typography>
                    </Box>
                    <Chip
                      label={invoice.status}
                      color={invoice.status === "paid" ? "success" : invoice.status === "overdue" ? "error" : "default"}
                    />
                    <DocumentUpload
                      targetType="invoice"
                      targetId={invoice.id}
                      onUploaded={(document) => documentAdded("invoice", invoice.id, document)}
                      onError={setError}
                    />
                  </Box>
                  {invoice.status !== "void" && Number(invoice.outstanding_amount) > 0 && (
                    <Box sx={{ display: "flex", gap: 1, mt: 2, flexWrap: "wrap" }}>
                      <TextField
                        select
                        size="small"
                        label="Received income"
                        value={allocationIncome[invoice.id] || ""}
                        onChange={(event) => setAllocationIncome({
                          ...allocationIncome,
                          [invoice.id]: event.target.value,
                        })}
                        sx={{ minWidth: 220 }}
                      >
                        {income
                          .filter((entry) => entry.original_currency === invoice.currency)
                          .map((entry) => (
                            <MenuItem key={entry.id} value={entry.id}>
                              {entry.received_date} · {entry.payer} · {money(entry.original_amount, entry.original_currency)}
                            </MenuItem>
                          ))}
                      </TextField>
                      <TextField
                        size="small"
                        type="number"
                        label="Allocate"
                        value={allocationAmount[invoice.id] || ""}
                        onChange={(event) => setAllocationAmount({
                          ...allocationAmount,
                          [invoice.id]: event.target.value,
                        })}
                      />
                      <Button onClick={() => allocate(invoice)}>Apply payment</Button>
                    </Box>
                  )}
                </CardContent>
              </Card>
            ))}
          </Stack>
        </>
      )}
    </Stack>
  );
}
